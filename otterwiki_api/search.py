"""Full-text search for the API, returning JSON-friendly results."""

import re

from otterwiki_api import get_pagename
from otterwiki_api.frontmatter import parse_frontmatter


SNIPPET_LENGTH = 150


def search_pages(storage, query, config):
    """Search all pages for a query string.

    PRD response shape: [{name, path, snippet, score}]
    """
    if not query or not query.strip():
        return []

    # Split query into individual terms for multi-term scoring
    terms = query.strip().split()
    try:
        patterns = [re.compile(re.escape(t), re.IGNORECASE) for t in terms]
        full_pattern = re.compile(re.escape(query), re.IGNORECASE)
    except re.error:
        return []

    files, _ = storage.list()
    results = []

    for filename in files:
        if not filename.endswith(".md"):
            continue

        try:
            content = storage.load(filename)
        except Exception:
            continue

        display_path = get_pagename(filename)

        frontmatter, body = parse_frontmatter(content)
        name = (frontmatter or {}).get("title", display_path.rsplit("/", 1)[-1])

        # Score: title match is worth more, count term matches
        title_score = 0
        body_score = 0
        for p in patterns:
            if p.search(name):
                title_score += 1
            body_matches = len(p.findall(body))
            body_score += body_matches

        # Exact phrase match bonus
        if full_pattern.search(name):
            title_score += len(terms)
        if full_pattern.search(body):
            body_score += len(terms)

        if title_score == 0 and body_score == 0:
            continue

        # Normalize to 0-1 range (title matches weighted 3x)
        max_possible = len(terms) * 4  # all terms match title + exact phrase
        raw_score = (title_score * 3 + min(body_score, len(terms) * 2)) / max(max_possible, 1)
        score = round(min(raw_score, 1.0), 2)

        # Build snippet around best match
        snippet = ""
        content_match = full_pattern.search(body) or (patterns[0].search(body) if patterns else None)
        if content_match:
            start = max(0, content_match.start() - SNIPPET_LENGTH // 3)
            end = min(len(body), content_match.end() + SNIPPET_LENGTH)
            snippet = body[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(body):
                snippet = snippet + "..."

        results.append({
            "name": name,
            "path": display_path,
            "snippet": snippet,
            "score": score,
        })

    # Sort by score descending
    results.sort(key=lambda r: r["score"], reverse=True)
    return results
