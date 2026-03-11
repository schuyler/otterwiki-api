"""API route handlers for /api/v1/."""

import os
from datetime import datetime, timezone

from flask import jsonify, request

from otterwiki.gitstorage import StorageError, StorageNotFound

from otterwiki_api import api_bp, _state, get_filename, get_pagename, get_author
from otterwiki_api.frontmatter import parse_frontmatter
from otterwiki_api.search import search_pages


def _commit_message(data, action, path):
    """Build commit message. If caller provides commit_message, use it as-is.
    Otherwise auto-generate: [api] action: page name.
    Callers (e.g. MCP server) can pass their own prefix via commit_message."""
    user_msg = (data or {}).get("commit_message")
    if user_msg:
        return user_msg
    return f"[api] {action}: {path}"


def _format_log_entry(entry):
    """Format a git log entry per PRD: {revision, author, date, message}."""
    dt = entry.get("datetime")
    return {
        "revision": entry.get("revision-full", ""),
        "author": entry.get("author_name", ""),
        "date": dt.isoformat() if dt else None,
        "message": entry.get("message", ""),
    }


# --- Page CRUD ---

@api_bp.route("/pages", methods=["GET"])
def list_pages():
    """PRD: returns {pages: [{name, path, category, tags, last_updated, content_length}], total}"""
    storage = _state["storage"]
    config = _state["app"].config

    files, _ = storage.list()

    # Filter params
    prefix = request.args.get("prefix", "").strip()
    category = request.args.get("category", "").strip()
    tag = request.args.get("tag", "").strip()
    updated_since = request.args.get("updated_since", "").strip()

    parsed_since = None
    if updated_since:
        try:
            parsed_since = datetime.fromisoformat(updated_since)
        except ValueError:
            return jsonify({"error": "Invalid updated_since format. Use ISO 8601."}), 422

    pages = []
    for filename in files:
        if not filename.endswith(".md"):
            continue

        page_path = filename[:-3]

        # Prefix filter
        if prefix:
            filter_prefix = prefix if config.get("RETAIN_PAGE_NAME_CASE", False) else prefix.lower()
            if not page_path.startswith(filter_prefix):
                continue

        # Load content for frontmatter-based filters and metadata
        try:
            content = storage.load(filename)
        except Exception:
            continue

        frontmatter, body = parse_frontmatter(content)
        fm = frontmatter or {}
        display_path = get_pagename(filename)
        name = fm.get("title", display_path.rsplit("/", 1)[-1])
        page_category = fm.get("category")
        page_tags = fm.get("tags", [])
        if isinstance(page_tags, str):
            page_tags = [t.strip() for t in page_tags.split(",")]

        # Category filter
        if category:
            if not page_category or page_category.lower() != category.lower():
                continue

        # Tag filter
        if tag:
            if tag.lower() not in [t.lower() for t in page_tags]:
                continue

        # Get metadata (single call, reused for filter and response)
        meta = None
        try:
            meta = storage.metadata(filename)
        except Exception:
            pass

        # Updated since filter
        if parsed_since and meta:
            page_dt = meta.get("datetime")
            if page_dt:
                if parsed_since.tzinfo and not page_dt.tzinfo:
                    page_dt = page_dt.replace(tzinfo=timezone.utc)
                elif not parsed_since.tzinfo and page_dt.tzinfo:
                    parsed_since = parsed_since.replace(tzinfo=timezone.utc)
                if page_dt < parsed_since:
                    continue

        # last_updated as date string per PRD
        last_updated = None
        if meta and meta.get("datetime"):
            last_updated = meta["datetime"].strftime("%Y-%m-%d")

        content_length = len(body.split())

        pages.append({
            "name": name,
            "path": display_path,
            "category": page_category,
            "tags": page_tags,
            "last_updated": last_updated,
            "content_length": content_length,
        })

    return jsonify({"pages": pages, "total": len(pages)})


@api_bp.route("/pages/<path:path>", methods=["GET"])
def get_page(path):
    """PRD: returns {name, path, content (raw with frontmatter), frontmatter, links_to, linked_from, revision, last_commit}"""
    storage = _state["storage"]
    filename = get_filename(path)

    revision = request.args.get("revision")

    try:
        content = storage.load(filename, revision=revision)
    except StorageNotFound:
        return jsonify({"error": f"Page not found: {path}"}), 404

    frontmatter, body = parse_frontmatter(content)
    display_path = get_pagename(filename)
    name = (frontmatter or {}).get("title", display_path.rsplit("/", 1)[-1])

    # Get last commit info
    last_commit = None
    rev_full = ""
    try:
        meta = storage.metadata(filename, revision=revision)
        rev_full = meta.get("revision-full", "")
        last_commit = {
            "revision": rev_full,
            "author": meta.get("author_name", ""),
            "date": meta["datetime"].isoformat() if meta.get("datetime") else None,
            "message": meta.get("message", ""),
        }
    except Exception:
        pass

    # WikiLink info — use raw path for index lookup, title-case for response
    index = _state.get("wikilink_index")
    raw_path = filename[:-3] if filename.endswith(".md") else filename
    if index:
        link_data = index.get_links_for_page(raw_path)
        links_to = [get_pagename(p) for p in link_data["outgoing"]]
        linked_from = [get_pagename(p) for p in link_data["incoming"]]
    else:
        links_to = []
        linked_from = []

    return jsonify({
        "name": name,
        "path": display_path,
        "content": content,  # raw markdown INCLUDING frontmatter per PRD
        "frontmatter": frontmatter,
        "links_to": links_to,
        "linked_from": linked_from,
        "revision": rev_full,
        "last_commit": last_commit,
    })


@api_bp.route("/pages/<path:path>", methods=["PUT"])
def put_page(path):
    """PRD: returns {name, path, revision, created}"""
    storage = _state["storage"]
    filename = get_filename(path)
    data = request.get_json(silent=True)

    if not data or "content" not in data:
        return jsonify({"error": "Request body must include 'content' field"}), 422

    content = data["content"]
    author = get_author()

    is_new = not storage.exists(filename)

    # Optimistic lock: require revision when overwriting an existing page
    if not is_new:
        revision = data.get("revision")
        if not revision:
            return jsonify({
                "error": "Revision required when updating an existing page. "
                         "Read the page first to get the current revision.",
            }), 409
        if len(revision) < 7:
            return jsonify({"error": "revision must be at least 7 characters"}), 422
        meta = storage.metadata(filename)
        current_rev = meta.get("revision-full", "")
        if not current_rev.startswith(revision):
            return jsonify({
                "error": "Revision mismatch: page has been modified since last read.",
                "current_revision": current_rev,
            }), 409

    action = "Create" if is_new else "Update"
    message = _commit_message(data, action, path)

    storage.store(filename=filename, content=content, message=message, author=author)

    # Update wikilink index
    index = _state.get("wikilink_index")
    if index:
        index.update_page(filename, content)

    # Get revision
    display_path = get_pagename(filename)
    rev_full = ""
    try:
        meta = storage.metadata(filename)
        rev_full = meta.get("revision-full", "")
    except Exception:
        pass

    # Derive name
    frontmatter, _ = parse_frontmatter(content)
    name = (frontmatter or {}).get("title", display_path.rsplit("/", 1)[-1])

    status = 201 if is_new else 200
    return jsonify({
        "name": name,
        "path": display_path,
        "revision": rev_full,
        "created": is_new,
    }), status


@api_bp.route("/pages/<path:path>", methods=["PATCH"])
def patch_page(path):
    """Edit-in-place with optimistic locking. Body: {revision, old_string, new_string, commit_message?}."""
    storage = _state["storage"]
    filename = get_filename(path)
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body is required"}), 422

    # Validate required fields
    for field in ("revision", "old_string", "new_string"):
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 422

    revision = data["revision"]
    old_string = data["old_string"]
    new_string = data["new_string"]

    if not old_string:
        return jsonify({"error": "old_string must not be empty"}), 422
    if not revision or len(revision) < 7:
        return jsonify({"error": "revision must be at least 7 characters"}), 422
    if old_string == new_string:
        return jsonify({"error": "old_string and new_string are identical"}), 422

    if not storage.exists(filename):
        return jsonify({"error": f"Page not found: {path}"}), 404

    # Optimistic lock: check revision matches
    meta = storage.metadata(filename)
    current_rev = meta.get("revision-full", "")
    if not current_rev.startswith(revision):
        return jsonify({
            "error": "Revision mismatch: page has been modified since last read.",
            "current_revision": current_rev,
        }), 409

    # Load content and find old_string
    content = storage.load(filename)
    count = content.count(old_string)
    if count == 0:
        return jsonify({"error": "old_string not found in page content"}), 422
    if count > 1:
        return jsonify({
            "error": f"old_string is ambiguous: found {count} occurrences. Provide a longer unique string."
        }), 422

    # Replace
    new_content = content.replace(old_string, new_string, 1)

    author = get_author()
    message = _commit_message(data, "Edit", path)
    storage.store(filename=filename, content=new_content, message=message, author=author)

    # Update wikilink index
    index = _state.get("wikilink_index")
    if index:
        index.update_page(filename, new_content)

    # Get new revision
    display_path = get_pagename(filename)
    rev_full = ""
    try:
        new_meta = storage.metadata(filename)
        rev_full = new_meta.get("revision-full", "")
    except Exception:
        pass

    frontmatter, _ = parse_frontmatter(new_content)
    name = (frontmatter or {}).get("title", display_path.rsplit("/", 1)[-1])

    return jsonify({
        "name": name,
        "path": display_path,
        "revision": rev_full,
    })


@api_bp.route("/pages/<path:path>", methods=["DELETE"])
def delete_page(path):
    storage = _state["storage"]
    filename = get_filename(path)

    if not storage.exists(filename):
        return jsonify({"error": f"Page not found: {path}"}), 404

    author = get_author()
    data = request.get_json(silent=True)
    message = _commit_message(data, "Delete", path)

    storage.delete(filename, message=message, author=author)

    # Update wikilink index
    index = _state.get("wikilink_index")
    if index:
        index.remove_page(filename)

    return jsonify({"deleted": True, "path": get_pagename(filename)})


# --- Rename ---

@api_bp.route("/pages/<path:path>/rename", methods=["POST"])
def rename_page(path):
    """Rename a page and rewrite all backreferences atomically."""
    storage = _state["storage"]
    index = _state.get("wikilink_index")

    old_filename = get_filename(path)
    if not storage.exists(old_filename):
        return jsonify({"error": f"Page not found: {path}"}), 404

    data = request.get_json(silent=True)
    if not data or "new_path" not in data:
        return jsonify({"error": "Request body must include 'new_path' field"}), 422

    new_path = data["new_path"].strip()
    if not new_path:
        return jsonify({"error": "new_path must not be empty"}), 422

    new_filename = get_filename(new_path)
    if old_filename == new_filename:
        return jsonify({"error": "new_path is the same as the current path"}), 422

    if storage.exists(new_filename):
        return jsonify({"error": f"A page already exists at: {new_path}"}), 409

    author = get_author()
    message = _commit_message(data, "Rename", f"{path} -> {new_path}")

    # --- Atomic rename + backreference rewrite ---
    try:
        # 1. git mv the page file (no commit yet)
        storage.rename(old_filename, new_filename, no_commit=True)

        # 2. Find and rewrite backreferences
        updated_filenames = []  # track actual filenames for commit
        updated_display = []    # track display paths for response
        old_page_path = old_filename[:-3] if old_filename.endswith(".md") else old_filename
        display_new_path = get_pagename(new_filename)

        if index:
            link_data = index.get_links_for_page(old_page_path)
            backrefs = link_data.get("incoming", [])

            for source_path in backrefs:
                # Self-link: page was already git-mv'd, load from new location
                if source_path == old_page_path:
                    source_filename = new_filename
                else:
                    source_filename = source_path + ".md"
                try:
                    content = storage.load(source_filename)
                except Exception:
                    continue  # skip if page was deleted between lookup and load

                new_content = index.rewrite_links(content, path, display_new_path)
                if new_content == content:
                    continue  # no actual link matches found

                # Write updated content to disk and stage it
                full_path = os.path.join(storage.path, source_filename)
                dirname = os.path.dirname(full_path)
                if dirname:
                    os.makedirs(dirname, exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                storage.repo.index.add([source_filename])
                updated_filenames.append(source_filename)
                updated_display.append(get_pagename(source_filename))

        # 3. Single atomic commit
        all_files = [old_filename, new_filename] + updated_filenames
        storage.commit(all_files, message, author, no_add=True)

    except StorageError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Roll back staged changes on unexpected failure
        try:
            storage.repo.git.reset("HEAD")
            storage.repo.git.checkout("--", ".")
        except Exception:
            pass
        return jsonify({"error": f"Rename failed: {e}"}), 500

    # 4. Update the wikilink index
    if index:
        index.rename_page(old_filename, new_filename)
        for source_filename in updated_filenames:
            try:
                content = storage.load(source_filename)
                index.update_page(source_filename, content)
            except Exception:
                pass

    # 5. Get new revision
    rev_full = ""
    try:
        meta = storage.metadata(new_filename)
        rev_full = meta.get("revision-full", "")
    except Exception:
        pass

    return jsonify({
        "old_path": get_pagename(old_filename),
        "new_path": display_new_path,
        "revision": rev_full,
        "updated_pages": updated_display,
    })


# --- History ---

@api_bp.route("/pages/<path:path>/history", methods=["GET"])
def page_history(path):
    """PRD: returns array of {revision, author, date, message}."""
    storage = _state["storage"]
    filename = get_filename(path)

    if not storage.exists(filename):
        return jsonify({"error": f"Page not found: {path}"}), 404

    max_count = request.args.get("limit", type=int)

    try:
        log = storage.log(filename, max_count=max_count)
    except StorageNotFound:
        return jsonify({"error": f"No history for: {path}"}), 404

    history = [_format_log_entry(entry) for entry in log]
    return jsonify({"path": get_pagename(filename), "history": history})


# --- Search ---

@api_bp.route("/search", methods=["GET"])
def search():
    """PRD: returns {results: [{name, path, snippet, score}], query, total}."""
    storage = _state["storage"]
    config = _state["app"].config
    query = request.args.get("q", "").strip()

    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 422

    results = search_pages(storage, query, config)
    return jsonify({"query": query, "results": results, "total": len(results)})


# --- Links ---

@api_bp.route("/links/<path:path>", methods=["GET"])
def page_links(path):
    """PRD: returns {links_to: [...], linked_from: [...]}."""
    index = _state.get("wikilink_index")
    if not index:
        return jsonify({"error": "WikiLink index not available"}), 500

    config = _state["app"].config
    retain_case = config.get("RETAIN_PAGE_NAME_CASE", False)
    lookup_path = path if retain_case else path.lower()

    link_data = index.get_links_for_page(lookup_path)
    return jsonify({
        "path": get_pagename(path),
        "links_to": [get_pagename(p) for p in link_data["outgoing"]],
        "linked_from": [get_pagename(p) for p in link_data["incoming"]],
    })


@api_bp.route("/links", methods=["GET"])
def full_link_graph():
    """PRD: returns {nodes: [...], edges: [...]}."""
    index = _state.get("wikilink_index")
    if not index:
        return jsonify({"error": "WikiLink index not available"}), 500

    graph = index.get_full_graph()
    return jsonify({
        "nodes": [get_pagename(n) for n in graph["nodes"]],
        "edges": [
            {"source": get_pagename(e["source"]), "target": get_pagename(e["target"])}
            for e in graph["edges"]
        ],
    })


# --- Changelog ---

@api_bp.route("/changelog", methods=["GET"])
def changelog():
    """PRD: returns array of {revision, author, date, message, pages_affected}."""
    storage = _state["storage"]
    limit = request.args.get("limit", 50, type=int)

    try:
        log = storage.log(max_count=limit)
    except StorageNotFound:
        return jsonify({"entries": [], "total": 0})

    entries = []
    for entry in log:
        pages_affected = []
        for f in entry.get("files", []):
            if f and f.endswith(".md"):
                pages_affected.append(get_pagename(f))

        e = _format_log_entry(entry)
        e["pages_affected"] = pages_affected
        entries.append(e)

    return jsonify({"entries": entries, "total": len(entries)})
