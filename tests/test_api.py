"""Tests for the otterwiki_api REST API plugin."""

import os
import pytest


API_KEY = "test-api-key-xyz"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture(autouse=True)
def set_api_key():
    os.environ["OTTERWIKI_API_KEY"] = API_KEY
    yield
    os.environ.pop("OTTERWIKI_API_KEY", None)


# --- Auth tests ---


class TestAuth:
    def test_health_no_auth(self, test_client):
        r = test_client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"

    def test_missing_auth_header(self, test_client):
        r = test_client.get("/api/v1/pages")
        assert r.status_code == 401
        assert "error" in r.get_json()

    def test_invalid_auth_header(self, test_client):
        r = test_client.get("/api/v1/pages", headers={"Authorization": "Basic abc"})
        assert r.status_code == 401

    def test_wrong_api_key(self, test_client):
        r = test_client.get("/api/v1/pages", headers={"Authorization": "Bearer wrong-key"})
        assert r.status_code == 401

    def test_valid_auth(self, test_client):
        r = test_client.get("/api/v1/pages", headers=AUTH_HEADERS)
        assert r.status_code == 200

    def test_no_api_key_configured(self, test_client):
        os.environ.pop("OTTERWIKI_API_KEY", None)
        r = test_client.get("/api/v1/pages", headers=AUTH_HEADERS)
        assert r.status_code == 500
        assert "not configured" in r.get_json()["error"]


# --- Page CRUD tests (PRD response shapes) ---


class TestPageCRUD:
    def test_create_page(self, test_client):
        """PUT returns {name, path, revision, created} per PRD."""
        r = test_client.put(
            "/api/v1/pages/test-page",
            json={"content": "Hello world"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["path"] == "test-page"
        assert data["created"] is True
        assert data["revision"]
        assert data["name"]

    def test_create_page_with_frontmatter(self, test_client):
        content = "---\ntitle: My Page\ntags: [api, test]\n---\nBody text here."
        r = test_client.put(
            "/api/v1/pages/fm-page",
            json={"content": content},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["name"] == "My Page"
        assert data["created"] is True

    def test_read_page_includes_frontmatter_in_content(self, test_client):
        """GET returns raw content INCLUDING frontmatter per PRD."""
        content = "---\ntitle: My Page\ntags: [api, test]\n---\nBody text here."
        test_client.put(
            "/api/v1/pages/fm-read",
            json={"content": content},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/fm-read", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        # Content includes frontmatter
        assert data["content"].startswith("---")
        assert "title: My Page" in data["content"]
        assert "Body text here." in data["content"]
        # Parsed frontmatter also present
        assert data["frontmatter"]["title"] == "My Page"
        assert data["frontmatter"]["tags"] == ["api", "test"]

    def test_read_page_prd_shape(self, test_client):
        """GET returns {name, path, content, frontmatter, links_to, linked_from, revision, last_commit}."""
        test_client.put(
            "/api/v1/pages/shape-test",
            json={"content": "Hello [[Other Page]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/shape-test", headers=AUTH_HEADERS)
        data = r.get_json()
        assert "name" in data
        assert "path" in data
        assert "content" in data
        assert "frontmatter" in data
        assert "links_to" in data
        assert "linked_from" in data
        assert "revision" in data
        assert "last_commit" in data
        assert data["last_commit"]["revision"]
        assert data["last_commit"]["author"]
        assert data["last_commit"]["date"]
        assert data["last_commit"]["message"]

    def test_read_page(self, test_client):
        test_client.put(
            "/api/v1/pages/read-test",
            json={"content": "Read me"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/read-test", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["content"] == "Read me"

    def test_read_nonexistent_page(self, test_client):
        r = test_client.get("/api/v1/pages/does-not-exist", headers=AUTH_HEADERS)
        assert r.status_code == 404

    def test_update_page(self, test_client):
        test_client.put(
            "/api/v1/pages/update-test",
            json={"content": "Version 1"},
            headers=AUTH_HEADERS,
        )
        r = test_client.put(
            "/api/v1/pages/update-test",
            json={"content": "Version 2"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["created"] is False

        # Verify content via GET
        r = test_client.get("/api/v1/pages/update-test", headers=AUTH_HEADERS)
        assert r.get_json()["content"] == "Version 2"

    def test_delete_page(self, test_client):
        test_client.put(
            "/api/v1/pages/delete-me",
            json={"content": "Goodbye"},
            headers=AUTH_HEADERS,
        )
        r = test_client.delete("/api/v1/pages/delete-me", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["deleted"] is True

        r = test_client.get("/api/v1/pages/delete-me", headers=AUTH_HEADERS)
        assert r.status_code == 404

    def test_delete_with_commit_message(self, test_client):
        """DELETE accepts commit_message in body per PRD."""
        test_client.put(
            "/api/v1/pages/del-msg",
            json={"content": "Will be deleted"},
            headers=AUTH_HEADERS,
        )
        r = test_client.delete(
            "/api/v1/pages/del-msg",
            json={"commit_message": "Removing obsolete page"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200

    def test_delete_nonexistent_page(self, test_client):
        r = test_client.delete("/api/v1/pages/no-such-page", headers=AUTH_HEADERS)
        assert r.status_code == 404

    def test_put_missing_content(self, test_client):
        r = test_client.put(
            "/api/v1/pages/bad-put",
            json={"title": "oops"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422

    def test_custom_commit_message(self, test_client):
        """PUT accepts commit_message field per PRD."""
        r = test_client.put(
            "/api/v1/pages/msg-test",
            json={"content": "Hello", "commit_message": "custom commit msg"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201

    def test_nested_page_path(self, test_client):
        r = test_client.put(
            "/api/v1/pages/projects/my-project",
            json={"content": "Nested page"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201
        assert r.get_json()["path"] == "projects/my-project"

        r = test_client.get("/api/v1/pages/projects/my-project", headers=AUTH_HEADERS)
        assert r.status_code == 200


# --- List tests (PRD: {name, path, category, tags, last_updated, content_length}) ---


class TestListPages:
    def _seed_pages(self, client):
        pages = [
            ("docs/intro", "---\ncategory: guide\ntags: [guide]\n---\nIntro text"),
            ("docs/advanced", "---\ncategory: guide\ntags: [guide, api]\n---\nAdvanced text"),
            ("blog/first-post", "---\ncategory: blog\ntags: [blog]\n---\nFirst blog post"),
        ]
        for path, content in pages:
            client.put(
                f"/api/v1/pages/{path}",
                json={"content": content},
                headers=AUTH_HEADERS,
            )

    def test_list_prd_shape(self, test_client):
        """List response has PRD fields: name, path, category, tags, last_updated, content_length, total."""
        self._seed_pages(test_client)
        r = test_client.get("/api/v1/pages", headers=AUTH_HEADERS)
        data = r.get_json()
        assert "total" in data
        assert data["total"] >= 3
        page = data["pages"][0]
        assert "name" in page
        assert "path" in page
        assert "category" in page
        assert "tags" in page
        assert "last_updated" in page
        assert "content_length" in page

    def test_list_all(self, test_client):
        self._seed_pages(test_client)
        r = test_client.get("/api/v1/pages", headers=AUTH_HEADERS)
        paths = [p["path"] for p in r.get_json()["pages"]]
        assert "docs/intro" in paths
        assert "blog/first-post" in paths

    def test_list_prefix_filter(self, test_client):
        self._seed_pages(test_client)
        r = test_client.get("/api/v1/pages?prefix=docs/", headers=AUTH_HEADERS)
        pages = r.get_json()["pages"]
        assert all(p["path"].startswith("docs/") for p in pages)
        assert len(pages) == 2

    def test_list_tag_filter(self, test_client):
        self._seed_pages(test_client)
        r = test_client.get("/api/v1/pages?tag=guide", headers=AUTH_HEADERS)
        pages = r.get_json()["pages"]
        assert len(pages) == 2
        paths = [p["path"] for p in pages]
        assert "docs/intro" in paths
        assert "docs/advanced" in paths

    def test_list_category_filter(self, test_client):
        """PRD: ?category= filter on frontmatter category field."""
        self._seed_pages(test_client)
        r = test_client.get("/api/v1/pages?category=blog", headers=AUTH_HEADERS)
        pages = r.get_json()["pages"]
        assert len(pages) == 1
        assert pages[0]["path"] == "blog/first-post"

    def test_list_updated_since_filter(self, test_client):
        self._seed_pages(test_client)
        r = test_client.get("/api/v1/pages?updated_since=2000-01-01", headers=AUTH_HEADERS)
        pages = r.get_json()["pages"]
        assert len(pages) >= 3

        r = test_client.get("/api/v1/pages?updated_since=2099-01-01", headers=AUTH_HEADERS)
        pages = r.get_json()["pages"]
        assert len(pages) == 0

    def test_list_invalid_updated_since(self, test_client):
        r = test_client.get("/api/v1/pages?updated_since=not-a-date", headers=AUTH_HEADERS)
        assert r.status_code == 422


# --- History tests (PRD: {revision, author, date, message}) ---


class TestHistory:
    def test_page_history(self, test_client):
        test_client.put(
            "/api/v1/pages/hist-page",
            json={"content": "v1"},
            headers=AUTH_HEADERS,
        )
        test_client.put(
            "/api/v1/pages/hist-page",
            json={"content": "v2"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/hist-page/history", headers=AUTH_HEADERS)
        assert r.status_code == 200
        history = r.get_json()["history"]
        assert len(history) == 2
        entry = history[0]
        assert entry["revision"]
        assert entry["date"]
        assert entry["author"]
        assert entry["message"]

    def test_history_nonexistent(self, test_client):
        r = test_client.get("/api/v1/pages/no-page/history", headers=AUTH_HEADERS)
        assert r.status_code == 404

    def test_history_limit(self, test_client):
        for i in range(5):
            test_client.put(
                "/api/v1/pages/multi-hist",
                json={"content": f"version {i}"},
                headers=AUTH_HEADERS,
            )
        r = test_client.get("/api/v1/pages/multi-hist/history?limit=2", headers=AUTH_HEADERS)
        assert len(r.get_json()["history"]) == 2


# --- Search tests (PRD: {name, path, snippet, score}) ---


class TestSearch:
    def test_search_finds_content(self, test_client):
        test_client.put(
            "/api/v1/pages/searchable",
            json={"content": "The quick brown fox jumps over the lazy dog"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/search?q=brown+fox", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        assert "total" in data
        results = data["results"]
        assert len(results) >= 1
        result = next(res for res in results if res["path"] == "searchable")
        assert "name" in result
        assert "snippet" in result
        assert "score" in result
        assert result["score"] > 0

    def test_search_no_query(self, test_client):
        r = test_client.get("/api/v1/search?q=", headers=AUTH_HEADERS)
        assert r.status_code == 422

    def test_search_no_results(self, test_client):
        r = test_client.get("/api/v1/search?q=xyznonexistent", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["total"] == 0

    def test_search_results_sorted_by_score(self, test_client):
        test_client.put(
            "/api/v1/pages/low-match",
            json={"content": "This page mentions fox once"},
            headers=AUTH_HEADERS,
        )
        test_client.put(
            "/api/v1/pages/high-match",
            json={"content": "fox fox fox fox fox fox fox"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/search?q=fox", headers=AUTH_HEADERS)
        results = r.get_json()["results"]
        if len(results) >= 2:
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True)


# --- WikiLink tests (PRD: links_to/linked_from) ---


class TestLinks:
    def test_outgoing_links(self, test_client):
        test_client.put(
            "/api/v1/pages/link-source",
            json={"content": "See [[Target Page]] and [[Another]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/links/link-source", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        assert "target page" in data["links_to"]
        assert "another" in data["links_to"]

    def test_incoming_links(self, test_client):
        test_client.put(
            "/api/v1/pages/source-a",
            json={"content": "Link to [[target-b]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/links/target-b", headers=AUTH_HEADERS)
        data = r.get_json()
        assert "source-a" in data["linked_from"]

    def test_full_link_graph(self, test_client):
        test_client.put(
            "/api/v1/pages/node-a",
            json={"content": "Links to [[Node B]]"},
            headers=AUTH_HEADERS,
        )
        test_client.put(
            "/api/v1/pages/node-b",
            json={"content": "Links to [[Node A]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/links", headers=AUTH_HEADERS)
        assert r.status_code == 200
        graph = r.get_json()
        assert "node a" in graph["nodes"]
        assert "node b" in graph["nodes"]
        assert len(graph["edges"]) >= 2

    def test_links_on_get_page(self, test_client):
        """GET /pages/<path> includes links_to and linked_from per PRD."""
        test_client.put(
            "/api/v1/pages/link-page",
            json={"content": "See [[Other]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/link-page", headers=AUTH_HEADERS)
        data = r.get_json()
        assert "other" in data["links_to"]
        assert isinstance(data["linked_from"], list)

    def test_links_updated_after_edit(self, test_client):
        test_client.put(
            "/api/v1/pages/editable",
            json={"content": "Links to [[OldTarget]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/links/editable", headers=AUTH_HEADERS)
        assert "oldtarget" in r.get_json()["links_to"]

        test_client.put(
            "/api/v1/pages/editable",
            json={"content": "Links to [[NewTarget]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/links/editable", headers=AUTH_HEADERS)
        data = r.get_json()
        assert "newtarget" in data["links_to"]
        assert "oldtarget" not in data["links_to"]

    def test_links_removed_after_delete(self, test_client):
        test_client.put(
            "/api/v1/pages/will-delete",
            json={"content": "Links to [[SomeTarget]]"},
            headers=AUTH_HEADERS,
        )
        test_client.delete("/api/v1/pages/will-delete", headers=AUTH_HEADERS)
        r = test_client.get("/api/v1/links/will-delete", headers=AUTH_HEADERS)
        data = r.get_json()
        assert len(data["links_to"]) == 0


# --- Changelog tests (PRD: {revision, author, date, message, pages_affected}) ---


class TestChangelog:
    def test_changelog_prd_shape(self, test_client):
        """Changelog entries have PRD fields: revision, author, date, message, pages_affected."""
        test_client.put(
            "/api/v1/pages/cl-page",
            json={"content": "Changelog test"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/changelog", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        assert "total" in data
        entries = data["entries"]
        assert len(entries) >= 1
        latest = entries[0]
        assert latest["revision"]
        assert latest["date"]
        assert latest["author"]
        assert "message" in latest
        assert "pages_affected" in latest

    def test_changelog_limit(self, test_client):
        for i in range(5):
            test_client.put(
                "/api/v1/pages/cl-limit-page",
                json={"content": f"v{i}"},
                headers=AUTH_HEADERS,
            )
        r = test_client.get("/api/v1/changelog?limit=2", headers=AUTH_HEADERS)
        assert len(r.get_json()["entries"]) == 2


# --- Revision tests ---


class TestRevision:
    def test_read_at_revision(self, test_client):
        test_client.put(
            "/api/v1/pages/rev-page",
            json={"content": "Original content"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/rev-page", headers=AUTH_HEADERS)
        rev1 = r.get_json()["last_commit"]["revision"]

        test_client.put(
            "/api/v1/pages/rev-page",
            json={"content": "Updated content"},
            headers=AUTH_HEADERS,
        )

        # Read at old revision
        r = test_client.get(f"/api/v1/pages/rev-page?revision={rev1}", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["content"] == "Original content"

        # Current version
        r = test_client.get("/api/v1/pages/rev-page", headers=AUTH_HEADERS)
        assert r.get_json()["content"] == "Updated content"

    def test_read_at_invalid_revision(self, test_client):
        test_client.put(
            "/api/v1/pages/rev-page2",
            json={"content": "Some content"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get(
            "/api/v1/pages/rev-page2?revision=deadbeef123456",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    def test_revision_matches_last_commit_revision(self, test_client):
        """Top-level revision and last_commit.revision should be the same full hash."""
        test_client.put(
            "/api/v1/pages/rev-consistency",
            json={"content": "Check consistency"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/rev-consistency", headers=AUTH_HEADERS)
        data = r.get_json()
        assert data["revision"] == data["last_commit"]["revision"]
        assert len(data["revision"]) == 40  # full SHA-1 hash


# --- Commit message convention tests ---


class TestCommitMessages:
    def test_auto_generated_create_message(self, test_client):
        """Auto-generated commit messages use [api] prefix."""
        test_client.put(
            "/api/v1/pages/auto-msg",
            json={"content": "Hello"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/auto-msg/history", headers=AUTH_HEADERS)
        msg = r.get_json()["history"][0]["message"]
        assert msg.startswith("[api]")

    def test_custom_commit_message_used_as_is(self, test_client):
        """Custom commit_message is used verbatim — caller controls the prefix."""
        test_client.put(
            "/api/v1/pages/custom-msg",
            json={"content": "Hello", "commit_message": "[mcp] Added initial content"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/custom-msg/history", headers=AUTH_HEADERS)
        msg = r.get_json()["history"][0]["message"]
        assert msg == "[mcp] Added initial content"

    def test_commit_message_no_prefix_required(self, test_client):
        """Caller can send commit_message without any prefix."""
        test_client.put(
            "/api/v1/pages/nopfx-msg",
            json={"content": "Hello", "commit_message": "Just a plain message"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/nopfx-msg/history", headers=AUTH_HEADERS)
        msg = r.get_json()["history"][0]["message"]
        assert msg == "Just a plain message"
