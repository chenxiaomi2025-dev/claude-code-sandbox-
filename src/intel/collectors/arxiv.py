"""arXiv collector via the public Atom API."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime

import feedparser

from intel.collectors.base import RawItem, http_client

API = "https://export.arxiv.org/api/query"


def fetch_arxiv(category: str, *, max_results: int = 50) -> Iterable[RawItem]:
    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    with http_client() as client:
        resp = client.get(API, params=params)
        resp.raise_for_status()
        data = resp.content
    feed = feedparser.parse(data)
    for entry in feed.entries:
        arxiv_id = entry.get("id", "")
        ext_id = f"arxiv::{category}::{hashlib.sha1(arxiv_id.encode('utf-8')).hexdigest()[:16]}"
        published = None
        if entry.get("published"):
            try:
                published = datetime.fromisoformat(entry.published.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                published = None
        authors = ", ".join(a.get("name", "") for a in entry.get("authors", []))
        yield RawItem(
            external_id=ext_id,
            url=entry.get("link", arxiv_id),
            title=(entry.get("title") or "").replace("\n", " ").strip(),
            summary=(entry.get("summary") or "").replace("\n", " ").strip(),
            author=authors or None,
            published_at=published,
            tags=["arxiv", category],
        )
