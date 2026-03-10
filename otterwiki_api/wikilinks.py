"""WikiLink parser and in-memory reverse index."""

import re


# Default WikiLink pattern: [[DisplayedText|PageName]] or [[PageName]]
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")


class WikiLinkIndex:
    """In-memory index of wikilinks across all pages."""

    def __init__(self, storage, config):
        self.storage = storage
        self.config = config
        # page_path -> set of target page paths (normalized, no .md)
        self.outgoing = {}
        # page_path -> set of source page paths that link to it
        self.incoming = {}

    def _normalize_target(self, target):
        """Normalize a wikilink target to a page path."""
        target = target.strip()
        if target.startswith("/"):
            target = target[1:]
        # Remove anchor fragments
        if "#" in target:
            target = target.split("#")[0]
        if not target:
            return None
        retain_case = self.config.get("RETAIN_PAGE_NAME_CASE", False)
        if not retain_case:
            target = target.lower()
        return target

    def _extract_links(self, content):
        """Extract wikilink targets from markdown content."""
        targets = set()
        wikilink_style = self.config.get("WIKILINK_STYLE", "")
        is_link_title = wikilink_style.upper().replace("_", "").strip() in [
            "LINKTITLE",
            "PAGENAMETITLE",
        ]

        for m in WIKILINK_RE.finditer(content):
            left, right = m.group(1), m.group(2)
            if right:
                # [[left|right]] - which is the link depends on style
                if is_link_title:
                    link = left
                else:
                    link = right
            else:
                link = left

            normalized = self._normalize_target(link)
            if normalized:
                targets.add(normalized)
        return targets

    def _page_path_from_filename(self, filename):
        """Convert 'some/page.md' to 'some/page'."""
        if filename.endswith(".md"):
            return filename[:-3]
        return filename

    def build(self):
        """Scan all pages and build the full index."""
        self.outgoing.clear()
        self.incoming.clear()

        files, _ = self.storage.list()
        for filename in files:
            if not filename.endswith(".md"):
                continue
            page_path = self._page_path_from_filename(filename)
            try:
                content = self.storage.load(filename)
            except Exception:
                continue
            targets = self._extract_links(content)
            self.outgoing[page_path] = targets
            for target in targets:
                if target not in self.incoming:
                    self.incoming[target] = set()
                self.incoming[target].add(page_path)

    def update_page(self, filename, content):
        """Update the index for a single page after create/edit."""
        page_path = self._page_path_from_filename(filename)

        # Remove old outgoing links
        old_targets = self.outgoing.pop(page_path, set())
        for target in old_targets:
            if target in self.incoming:
                self.incoming[target].discard(page_path)
                if not self.incoming[target]:
                    del self.incoming[target]

        # Add new outgoing links
        targets = self._extract_links(content)
        self.outgoing[page_path] = targets
        for target in targets:
            if target not in self.incoming:
                self.incoming[target] = set()
            self.incoming[target].add(page_path)

    def remove_page(self, filename):
        """Remove a page from the index."""
        page_path = self._page_path_from_filename(filename)

        old_targets = self.outgoing.pop(page_path, set())
        for target in old_targets:
            if target in self.incoming:
                self.incoming[target].discard(page_path)
                if not self.incoming[target]:
                    del self.incoming[target]

    def get_links_for_page(self, page_path):
        """Get outgoing and incoming links for a page."""
        return {
            "outgoing": sorted(self.outgoing.get(page_path, set())),
            "incoming": sorted(self.incoming.get(page_path, set())),
        }

    def get_full_graph(self):
        """Get the full link graph."""
        nodes = set()
        edges = []
        for source, targets in self.outgoing.items():
            nodes.add(source)
            for target in targets:
                nodes.add(target)
                edges.append({"source": source, "target": target})
        return {
            "nodes": sorted(nodes),
            "edges": edges,
        }
