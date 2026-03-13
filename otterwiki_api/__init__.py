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
    """Convert a URL page path to the on-disk filename. Delegates to otterwiki core."""
    from otterwiki.helper import get_filename as _core
    return _core(pagepath)


def resolve_filename(pagepath):
    """Find the actual on-disk filename for a page path.

    Tries the normalized filename first (e.g. spaces→underscores), then
    falls back to the literal path. This handles migration cases where
    files were created before normalization was enabled.
    """
    from otterwiki.util import clean_slashes

    storage = _state["storage"]
    normalized = get_filename(pagepath)
    if storage.exists(normalized):
        return normalized

    # Fallback: try the literal path without normalization
    literal = clean_slashes(pagepath)
    if not literal.endswith(".md"):
        literal = f"{literal}.md"
    if storage.exists(literal):
        return literal

    return normalized  # Return normalized even if not found (caller handles 404)


def get_pagename(filepath):
    """Derive full display path from a filepath. Delegates to otterwiki core."""
    from otterwiki.helper import get_pagename as _core
    return _core(filepath, full=True)


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
