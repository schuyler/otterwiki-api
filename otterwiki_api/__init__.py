"""
Otterwiki REST API Plugin

Adds JSON CRUD endpoints under /api/v1/ to An Otter Wiki.
"""

import os

from flask import Blueprint, jsonify

from otterwiki.plugins import hookimpl, plugin_manager

api_bp = Blueprint("otterwiki_api", __name__, url_prefix="/api/v1")

# Shared state populated during setup()
_state = {
    "app": None,
    "storage": None,
    "db": None,
    "wikilink_index": None,
}


def get_author():
    name = os.environ.get("OTTERWIKI_API_AUTHOR_NAME", "Claude (MCP)")
    email = os.environ.get("OTTERWIKI_API_AUTHOR_EMAIL", "claude-mcp@otterwiki.local")
    return (name, email)


def get_filename(pagepath):
    """Convert a URL page path to the on-disk filename, respecting RETAIN_PAGE_NAME_CASE."""
    app = _state["app"]
    retain_case = app.config.get("RETAIN_PAGE_NAME_CASE", False) if app else False
    p = pagepath if retain_case else pagepath.lower()
    # Clean slashes
    parts = [part for part in p.split("/") if part]
    p = "/".join(parts)
    if not p.endswith(".md"):
        p = f"{p}.md"
    return p


def get_pagename(filepath):
    """Derive display name from a filepath like 'some/page.md' -> 'Some/Page'."""
    if filepath.endswith(".md"):
        filepath = filepath[:-3]
    parts = filepath.split("/")
    app = _state["app"]
    retain_case = app.config.get("RETAIN_PAGE_NAME_CASE", False) if app else False
    if not retain_case:
        parts = [p.title() for p in parts]
    return "/".join(parts)


@api_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


class OtterwikiApiPlugin:
    @hookimpl
    def setup(self, app, db, storage):
        _state["app"] = app
        _state["storage"] = storage
        _state["db"] = db

        # Import routes and auth to register them on the blueprint
        import otterwiki_api.auth  # noqa: F401
        import otterwiki_api.routes  # noqa: F401

        app.register_blueprint(api_bp)

        # Build wikilink index after all pages are available
        from otterwiki_api.wikilinks import WikiLinkIndex

        index = WikiLinkIndex(storage, app.config)
        index.build()
        _state["wikilink_index"] = index


plugin_manager.register(OtterwikiApiPlugin())
