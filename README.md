# otterwiki-api

A REST API plugin for [An Otter Wiki](https://otterwiki.com/) that adds JSON
CRUD endpoints under `/api/v1/`.

This exists so that automated tools — MCP servers, scripts, bots — can read and
write wiki pages without going through the web UI. It hooks into Otterwiki's
plugin system, so you don't need to fork or patch anything.

## Synopsis

```sh
# Health check (no auth required)
curl http://localhost:8080/api/v1/health

# List all pages
curl -H "Authorization: Bearer $OTTERWIKI_API_KEY" \
  http://localhost:8080/api/v1/pages

# Get a page
curl -H "Authorization: Bearer $OTTERWIKI_API_KEY" \
  http://localhost:8080/api/v1/pages/some/page

# Create or update a page
curl -X PUT -H "Authorization: Bearer $OTTERWIKI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"content": "# Hello\n\nThis is a page."}' \
  http://localhost:8080/api/v1/pages/some/page
```

## Installation

```sh
pip install otterwiki-api
```

Or install from source:

```sh
pip install -e .
```

The plugin registers itself via Otterwiki's entry point system. No configuration
in Otterwiki itself is needed — just install the package and restart.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `OTTERWIKI_API_KEY` | Bearer token for API authentication | *(required)* |
| `OTTERWIKI_API_AUTHOR_NAME` | Git author name for commits | `Claude (MCP)` |
| `OTTERWIKI_API_AUTHOR_EMAIL` | Git author email for commits | `claude-mcp@otterwiki.local` |

All endpoints except `/health` require a valid `Authorization: Bearer <key>`
header.

## Endpoints

### Pages

- **`GET /api/v1/pages`** — List pages. Supports `prefix`, `category`, `tag`,
  and `updated_since` query filters, composed with AND logic.
- **`GET /api/v1/pages/<path>`** — Get a page, including raw content,
  parsed frontmatter, and wikilink data. Supports `?revision=<sha>`.
- **`PUT /api/v1/pages/<path>`** — Create or update a page. Body:
  `{"content": "...", "commit_message": "..."}`. Returns 201 on create, 200 on
  update.
- **`DELETE /api/v1/pages/<path>`** — Delete a page.

### History

- **`GET /api/v1/pages/<path>/history`** — Commit history for a page. Supports
  `?limit=N`.
- **`GET /api/v1/changelog`** — Site-wide commit log. Supports `?limit=N`
  (default 50).

### Search

- **`GET /api/v1/search?q=<query>`** — Full-text search across all pages.
  Returns results ranked by relevance with snippets.

### Links

- **`GET /api/v1/links/<path>`** — Incoming and outgoing wikilinks for a page.
- **`GET /api/v1/links`** — Full wikilink graph as `{nodes, edges}`.

## Features

- **YAML frontmatter** — Parses `title`, `category`, and `tags` from page
  frontmatter for filtering and display.
- **WikiLink index** — Maintains an in-memory bidirectional link graph, updated
  incrementally on page create/edit/delete. Supports `[[Link]]` and
  `[[Display|Link]]` syntax.
- **Revision access** — Read any page at a specific git revision.
- **Timing-safe auth** — Uses `hmac.compare_digest()` for token comparison.

## Testing

```sh
pip install -e '.[dev]'
pytest
```

The test suite sets up temporary Otterwiki instances with their own git repos,
so no running wiki is needed.

## License

It's MIT licensed, yo. See [LICENSE](LICENSE) for details.
