"""Hacker News top-stories collector via the official Firebase API."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from intel.collectors.base import RawItem, http_client

TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


def fetch_hn(*, min_points: int = 200, limit: int = 80) -> Iterable[RawItem]:
    with http_client() as client:
        ids = client.get(TOP).json()[:limit]
        for sid in ids:
            try:
                item = client.get(ITEM.format(id=sid)).json()
            except Exception:
                continue
            if not item or item.get("type") != "story":
                continue
            score = item.get("score", 0) or 0
            if score < min_points:
                continue
            ts = item.get("time")
            published = datetime.utcfromtimestamp(ts) if ts else None
            url = item.get("url") or f"https://news.ycombinator.com/item?id={sid}"
            yield RawItem(
                external_id=f"hn::{sid}",
                url=url,
                title=(item.get("title") or "").strip(),
                summary=f"score={score} comments={item.get('descendants', 0)}",
                author=item.get("by"),
                published_at=published,
                tags=["hackernews", f"score:{score}"],
            )
