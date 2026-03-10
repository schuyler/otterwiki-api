"""API route handlers for /api/v1/."""

from datetime import datetime, timezone

from flask import jsonify, request

from otterwiki.gitstorage import StorageNotFound

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
        name = fm.get("title", get_pagename(filename))
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
            "path": page_path,
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
    page_path = filename[:-3] if filename.endswith(".md") else filename
    name = (frontmatter or {}).get("title", get_pagename(filename))

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

    # WikiLink info
    index = _state.get("wikilink_index")
    if index:
        link_data = index.get_links_for_page(page_path)
        links_to = link_data["outgoing"]
        linked_from = link_data["incoming"]
    else:
        links_to = []
        linked_from = []

    return jsonify({
        "name": name,
        "path": page_path,
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
    action = "Create" if is_new else "Update"
    message = _commit_message(data, action, path)

    storage.store(filename=filename, content=content, message=message, author=author)

    # Update wikilink index
    index = _state.get("wikilink_index")
    if index:
        index.update_page(filename, content)

    # Get revision
    page_path = filename[:-3] if filename.endswith(".md") else filename
    rev_short = ""
    try:
        meta = storage.metadata(filename)
        rev_short = meta.get("revision", "")
    except Exception:
        pass

    # Derive name
    frontmatter, _ = parse_frontmatter(content)
    name = (frontmatter or {}).get("title", get_pagename(filename))

    status = 201 if is_new else 200
    return jsonify({
        "name": name,
        "path": page_path,
        "revision": rev_short,
        "created": is_new,
    }), status


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

    return jsonify({"deleted": True, "path": path})


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
    return jsonify({"path": path, "history": history})


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
    page_path = path if retain_case else path.lower()

    link_data = index.get_links_for_page(page_path)
    return jsonify({
        "path": page_path,
        "links_to": link_data["outgoing"],
        "linked_from": link_data["incoming"],
    })


@api_bp.route("/links", methods=["GET"])
def full_link_graph():
    """PRD: returns {nodes: [...], edges: [...]}."""
    index = _state.get("wikilink_index")
    if not index:
        return jsonify({"error": "WikiLink index not available"}), 500

    graph = index.get_full_graph()
    return jsonify(graph)


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
                pages_affected.append(f[:-3])

        e = _format_log_entry(entry)
        e["pages_affected"] = pages_affected
        entries.append(e)

    return jsonify({"entries": entries, "total": len(entries)})
