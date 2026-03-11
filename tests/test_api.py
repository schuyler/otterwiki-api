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
    def _create_and_get_rev(self, client, path, content):
        """Helper: create a page and return its revision SHA."""
        client.put(f"/api/v1/pages/{path}", json={"content": content}, headers=AUTH_HEADERS)
        r = client.get(f"/api/v1/pages/{path}", headers=AUTH_HEADERS)
        return r.get_json()["revision"]

    def test_create_page(self, test_client):
        """PUT returns {name, path, revision, created} per PRD."""
        r = test_client.put(
            "/api/v1/pages/test-page",
            json={"content": "Hello world"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["path"] == "Test-Page"
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
        rev = self._create_and_get_rev(test_client, "update-test", "Version 1")
        r = test_client.put(
            "/api/v1/pages/update-test",
            json={"content": "Version 2", "revision": rev},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["created"] is False

        # Verify content via GET
        r = test_client.get("/api/v1/pages/update-test", headers=AUTH_HEADERS)
        assert r.get_json()["content"] == "Version 2"

    def test_update_without_revision_409(self, test_client):
        self._create_and_get_rev(test_client, "no-rev-update", "Original")
        r = test_client.put(
            "/api/v1/pages/no-rev-update",
            json={"content": "Updated"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 409
        data = r.get_json()
        assert "Revision required" in data["error"]
        assert "current_revision" not in data

    def test_update_empty_revision_409(self, test_client):
        self._create_and_get_rev(test_client, "empty-rev", "Original")
        r = test_client.put(
            "/api/v1/pages/empty-rev",
            json={"content": "Updated", "revision": ""},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 409
        assert "Revision required" in r.get_json()["error"]

    def test_update_wrong_revision_409(self, test_client):
        self._create_and_get_rev(test_client, "wrong-rev", "Original")
        r = test_client.put(
            "/api/v1/pages/wrong-rev",
            json={"content": "Updated", "revision": "deadbeef00000000"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 409
        data = r.get_json()
        assert "Revision mismatch" in data["error"]
        assert "current_revision" in data

    def test_update_short_revision_422(self, test_client):
        self._create_and_get_rev(test_client, "short-rev", "Original")
        r = test_client.put(
            "/api/v1/pages/short-rev",
            json={"content": "Updated", "revision": "abc"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "at least 7" in r.get_json()["error"]

    def test_create_without_revision_succeeds(self, test_client):
        """Creating a new page should work without a revision."""
        r = test_client.put(
            "/api/v1/pages/brand-new",
            json={"content": "Fresh page"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 201
        assert r.get_json()["created"] is True

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
        assert r.get_json()["path"] == "Projects/My-Project"

        r = test_client.get("/api/v1/pages/projects/my-project", headers=AUTH_HEADERS)
        assert r.status_code == 200


# --- Patch (edit-in-place) tests ---


class TestPatchPage:
    def _create_and_get_rev(self, client, path, content):
        """Helper: create a page and return its revision SHA."""
        client.put(f"/api/v1/pages/{path}", json={"content": content}, headers=AUTH_HEADERS)
        r = client.get(f"/api/v1/pages/{path}", headers=AUTH_HEADERS)
        return r.get_json()["revision"]

    def test_successful_edit(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-test", "Hello world")
        r = test_client.patch(
            "/api/v1/pages/patch-test",
            json={"revision": rev, "old_string": "Hello", "new_string": "Goodbye"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["path"] == "Patch-Test"
        assert data["revision"]
        assert data["revision"] != rev

        # Verify content changed
        r = test_client.get("/api/v1/pages/patch-test", headers=AUTH_HEADERS)
        assert r.get_json()["content"] == "Goodbye world"

    def test_edit_frontmatter(self, test_client):
        content = "---\nconfidence: medium\n---\nBody text"
        rev = self._create_and_get_rev(test_client, "patch-fm", content)
        r = test_client.patch(
            "/api/v1/pages/patch-fm",
            json={"revision": rev, "old_string": "confidence: medium", "new_string": "confidence: high"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        r = test_client.get("/api/v1/pages/patch-fm", headers=AUTH_HEADERS)
        assert "confidence: high" in r.get_json()["content"]

    def test_delete_text_with_empty_new_string(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-del", "Keep this. Remove this.")
        r = test_client.patch(
            "/api/v1/pages/patch-del",
            json={"revision": rev, "old_string": " Remove this.", "new_string": ""},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        r = test_client.get("/api/v1/pages/patch-del", headers=AUTH_HEADERS)
        assert r.get_json()["content"] == "Keep this."

    def test_revision_mismatch_409(self, test_client):
        self._create_and_get_rev(test_client, "patch-conflict", "Original")
        r = test_client.patch(
            "/api/v1/pages/patch-conflict",
            json={"revision": "deadbeef00000000", "old_string": "Original", "new_string": "Changed"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 409
        data = r.get_json()
        assert "Revision mismatch" in data["error"]
        assert "current_revision" in data

    def test_old_string_not_found_422(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-missing", "Hello world")
        r = test_client.patch(
            "/api/v1/pages/patch-missing",
            json={"revision": rev, "old_string": "nonexistent text", "new_string": "replacement"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "not found" in r.get_json()["error"]

    def test_ambiguous_old_string_422(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-ambig", "foo bar foo")
        r = test_client.patch(
            "/api/v1/pages/patch-ambig",
            json={"revision": rev, "old_string": "foo", "new_string": "baz"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "ambiguous" in r.get_json()["error"]
        assert "2" in r.get_json()["error"]

    def test_page_not_found_404(self, test_client):
        r = test_client.patch(
            "/api/v1/pages/no-such-page",
            json={"revision": "abcdef1234567", "old_string": "x", "new_string": "y"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    def test_missing_required_field(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-fields", "content")
        r = test_client.patch(
            "/api/v1/pages/patch-fields",
            json={"revision": rev, "old_string": "content"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "new_string" in r.get_json()["error"]

    def test_identical_strings_422(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-same", "Hello")
        r = test_client.patch(
            "/api/v1/pages/patch-same",
            json={"revision": rev, "old_string": "Hello", "new_string": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "identical" in r.get_json()["error"]

    def test_custom_commit_message(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-msg", "Alpha")
        test_client.patch(
            "/api/v1/pages/patch-msg",
            json={
                "revision": rev,
                "old_string": "Alpha",
                "new_string": "Beta",
                "commit_message": "[mcp] custom edit message",
            },
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/pages/patch-msg/history", headers=AUTH_HEADERS)
        msg = r.get_json()["history"][0]["message"]
        assert msg == "[mcp] custom edit message"

    def test_short_revision_accepted(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-short-rev", "Content here")
        short_rev = rev[:7]
        r = test_client.patch(
            "/api/v1/pages/patch-short-rev",
            json={"revision": short_rev, "old_string": "Content", "new_string": "New content"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200

    def test_wikilink_index_updated(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-links", "See [[OldTarget]]")
        test_client.patch(
            "/api/v1/pages/patch-links",
            json={"revision": rev, "old_string": "[[OldTarget]]", "new_string": "[[NewTarget]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/links/patch-links", headers=AUTH_HEADERS)
        data = r.get_json()
        assert "Newtarget" in data["links_to"]
        assert "Oldtarget" not in data["links_to"]

    def test_empty_revision_rejected(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-empty-rev", "Hello")
        r = test_client.patch(
            "/api/v1/pages/patch-empty-rev",
            json={"revision": "", "old_string": "Hello", "new_string": "Bye"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "at least 7" in r.get_json()["error"]

    def test_too_short_revision_rejected(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-short", "Hello")
        r = test_client.patch(
            "/api/v1/pages/patch-short",
            json={"revision": rev[:3], "old_string": "Hello", "new_string": "Bye"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "at least 7" in r.get_json()["error"]

    def test_empty_old_string_rejected(self, test_client):
        rev = self._create_and_get_rev(test_client, "patch-empty-old", "Hello")
        r = test_client.patch(
            "/api/v1/pages/patch-empty-old",
            json={"revision": rev, "old_string": "", "new_string": "something"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "empty" in r.get_json()["error"]


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
        assert "Docs/Intro" in paths
        assert "Blog/First-Post" in paths

    def test_list_prefix_filter(self, test_client):
        self._seed_pages(test_client)
        r = test_client.get("/api/v1/pages?prefix=docs/", headers=AUTH_HEADERS)
        pages = r.get_json()["pages"]
        assert all(p["path"].startswith("Docs/") for p in pages)
        assert len(pages) == 2

    def test_list_tag_filter(self, test_client):
        self._seed_pages(test_client)
        r = test_client.get("/api/v1/pages?tag=guide", headers=AUTH_HEADERS)
        pages = r.get_json()["pages"]
        assert len(pages) == 2
        paths = [p["path"] for p in pages]
        assert "Docs/Intro" in paths
        assert "Docs/Advanced" in paths

    def test_list_category_filter(self, test_client):
        """PRD: ?category= filter on frontmatter category field."""
        self._seed_pages(test_client)
        r = test_client.get("/api/v1/pages?category=blog", headers=AUTH_HEADERS)
        pages = r.get_json()["pages"]
        assert len(pages) == 1
        assert pages[0]["path"] == "Blog/First-Post"

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
    def _create_and_get_rev(self, client, path, content):
        """Helper: create a page and return its revision SHA."""
        client.put(f"/api/v1/pages/{path}", json={"content": content}, headers=AUTH_HEADERS)
        r = client.get(f"/api/v1/pages/{path}", headers=AUTH_HEADERS)
        return r.get_json()["revision"]

    def test_page_history(self, test_client):
        rev = self._create_and_get_rev(test_client, "hist-page", "v1")
        test_client.put(
            "/api/v1/pages/hist-page",
            json={"content": "v2", "revision": rev},
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
        rev = self._create_and_get_rev(test_client, "multi-hist", "version 0")
        for i in range(1, 5):
            r = test_client.put(
                "/api/v1/pages/multi-hist",
                json={"content": f"version {i}", "revision": rev},
                headers=AUTH_HEADERS,
            )
            rev = r.get_json()["revision"]
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
        result = next(res for res in results if res["path"] == "Searchable")
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
        assert "Target Page" in data["links_to"]
        assert "Another" in data["links_to"]

    def test_incoming_links(self, test_client):
        test_client.put(
            "/api/v1/pages/source-a",
            json={"content": "Link to [[target-b]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/links/target-b", headers=AUTH_HEADERS)
        data = r.get_json()
        assert "Source-A" in data["linked_from"]

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
        assert "Node A" in graph["nodes"]
        assert "Node B" in graph["nodes"]
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
        assert "Other" in data["links_to"]
        assert isinstance(data["linked_from"], list)

    def test_links_updated_after_edit(self, test_client):
        test_client.put(
            "/api/v1/pages/editable",
            json={"content": "Links to [[OldTarget]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/links/editable", headers=AUTH_HEADERS)
        assert "Oldtarget" in r.get_json()["links_to"]

        r = test_client.get("/api/v1/pages/editable", headers=AUTH_HEADERS)
        rev = r.get_json()["revision"]
        test_client.put(
            "/api/v1/pages/editable",
            json={"content": "Links to [[NewTarget]]", "revision": rev},
            headers=AUTH_HEADERS,
        )
        r = test_client.get("/api/v1/links/editable", headers=AUTH_HEADERS)
        data = r.get_json()
        assert "Newtarget" in data["links_to"]
        assert "Oldtarget" not in data["links_to"]

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
        test_client.put(
            "/api/v1/pages/cl-limit-page",
            json={"content": "v0"},
            headers=AUTH_HEADERS,
        )
        for i in range(1, 5):
            r = test_client.get("/api/v1/pages/cl-limit-page", headers=AUTH_HEADERS)
            rev = r.get_json()["revision"]
            test_client.put(
                "/api/v1/pages/cl-limit-page",
                json={"content": f"v{i}", "revision": rev},
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
            json={"content": "Updated content", "revision": rev1},
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


# --- Rename tests ---


class TestRenamePage:
    def test_basic_rename(self, test_client):
        """Rename moves content to new path."""
        test_client.put(
            "/api/v1/pages/old-name",
            json={"content": "Hello world"},
            headers=AUTH_HEADERS,
        )
        r = test_client.post(
            "/api/v1/pages/old-name/rename",
            json={"new_path": "new-name"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["old_path"] == "Old-Name"
        assert data["new_path"] == "New-Name"
        assert data["revision"]
        assert isinstance(data["updated_pages"], list)

        # Old path gone, new path has content
        r = test_client.get("/api/v1/pages/old-name", headers=AUTH_HEADERS)
        assert r.status_code == 404
        r = test_client.get("/api/v1/pages/new-name", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["content"] == "Hello world"

    def test_rename_rewrites_backreferences(self, test_client):
        """Pages linking to old name have their wikilinks updated."""
        test_client.put(
            "/api/v1/pages/target",
            json={"content": "I am the target"},
            headers=AUTH_HEADERS,
        )
        test_client.put(
            "/api/v1/pages/linker",
            json={"content": "See [[Target]] for details"},
            headers=AUTH_HEADERS,
        )
        r = test_client.post(
            "/api/v1/pages/target/rename",
            json={"new_path": "new-target"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "Linker" in data["updated_pages"]

        # Verify the linking page was rewritten
        r = test_client.get("/api/v1/pages/linker", headers=AUTH_HEADERS)
        content = r.get_json()["content"]
        assert "[[New-Target]]" in content
        assert "[[Target]]" not in content

    def test_rename_preserves_display_text(self, test_client):
        """Display text in [[Display|Link]] is preserved."""
        test_client.put(
            "/api/v1/pages/actors/iran",
            json={"content": "Iran page"},
            headers=AUTH_HEADERS,
        )
        test_client.put(
            "/api/v1/pages/summary",
            json={"content": "The [[Islamic Republic|Actors/Iran]] is a key actor"},
            headers=AUTH_HEADERS,
        )
        r = test_client.post(
            "/api/v1/pages/actors/iran/rename",
            json={"new_path": "actors/iran-islamic-republic"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200

        r = test_client.get("/api/v1/pages/summary", headers=AUTH_HEADERS)
        content = r.get_json()["content"]
        assert "[[Islamic Republic|Actors/Iran-Islamic-Republic]]" in content

    def test_rename_preserves_anchors(self, test_client):
        """Anchors in wikilinks are preserved: [[Page#section]] -> [[NewPage#section]]."""
        test_client.put(
            "/api/v1/pages/topic",
            json={"content": "# Section\nContent"},
            headers=AUTH_HEADERS,
        )
        test_client.put(
            "/api/v1/pages/referrer",
            json={"content": "See [[Topic#section]] for details"},
            headers=AUTH_HEADERS,
        )
        r = test_client.post(
            "/api/v1/pages/topic/rename",
            json={"new_path": "new-topic"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200

        r = test_client.get("/api/v1/pages/referrer", headers=AUTH_HEADERS)
        content = r.get_json()["content"]
        assert "[[New-Topic#section]]" in content

    def test_rename_nonexistent_404(self, test_client):
        r = test_client.post(
            "/api/v1/pages/does-not-exist/rename",
            json={"new_path": "whatever"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    def test_rename_target_exists_409(self, test_client):
        test_client.put(
            "/api/v1/pages/page-a",
            json={"content": "A"},
            headers=AUTH_HEADERS,
        )
        test_client.put(
            "/api/v1/pages/page-b",
            json={"content": "B"},
            headers=AUTH_HEADERS,
        )
        r = test_client.post(
            "/api/v1/pages/page-a/rename",
            json={"new_path": "page-b"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 409

    def test_rename_same_path_422(self, test_client):
        test_client.put(
            "/api/v1/pages/same-page",
            json={"content": "Content"},
            headers=AUTH_HEADERS,
        )
        r = test_client.post(
            "/api/v1/pages/same-page/rename",
            json={"new_path": "same-page"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert "same" in r.get_json()["error"]

    def test_rename_missing_new_path_422(self, test_client):
        test_client.put(
            "/api/v1/pages/some-page",
            json={"content": "Content"},
            headers=AUTH_HEADERS,
        )
        r = test_client.post(
            "/api/v1/pages/some-page/rename",
            json={},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422

    def test_rename_updates_link_index(self, test_client):
        """After rename, the wikilink index reflects the new path."""
        test_client.put(
            "/api/v1/pages/indexed-page",
            json={"content": "Links to [[Some Target]]"},
            headers=AUTH_HEADERS,
        )
        test_client.post(
            "/api/v1/pages/indexed-page/rename",
            json={"new_path": "renamed-page"},
            headers=AUTH_HEADERS,
        )
        # The renamed page's outgoing links should still be tracked
        r = test_client.get("/api/v1/links/renamed-page", headers=AUTH_HEADERS)
        data = r.get_json()
        assert "Some Target" in data["links_to"]

    def test_rename_atomic_single_commit(self, test_client):
        """Rename + backreference updates happen in a single commit."""
        test_client.put(
            "/api/v1/pages/atomic-target",
            json={"content": "Target page"},
            headers=AUTH_HEADERS,
        )
        test_client.put(
            "/api/v1/pages/atomic-linker",
            json={"content": "See [[Atomic-Target]]"},
            headers=AUTH_HEADERS,
        )
        r = test_client.post(
            "/api/v1/pages/atomic-target/rename",
            json={"new_path": "atomic-renamed"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        rev = r.get_json()["revision"]

        # Both the renamed page and the updated linker should share the same commit
        r = test_client.get("/api/v1/pages/atomic-linker", headers=AUTH_HEADERS)
        linker_rev = r.get_json()["last_commit"]["revision"]
        assert linker_rev == rev

    def test_rename_nested_path(self, test_client):
        """Rename works with nested paths."""
        test_client.put(
            "/api/v1/pages/actors/old-actor",
            json={"content": "Actor page"},
            headers=AUTH_HEADERS,
        )
        r = test_client.post(
            "/api/v1/pages/actors/old-actor/rename",
            json={"new_path": "actors/new-actor"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        r = test_client.get("/api/v1/pages/actors/new-actor", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["content"] == "Actor page"
