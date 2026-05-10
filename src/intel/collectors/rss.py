"""RSS / Atom feed collector."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime

import feedparser
from dateutil import parser as dateparser

from intel.collectors.base import RawItem, http_client


def _parse_date(entry) -> datetime | None:
    for key in ("published", "updated", "created"):
        v = entry.get(key)
        if v:
            try:
                return dateparser.parse(v).replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
    return None


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    from bs4 import BeautifulSoup

    return BeautifulSoup(text, "lxml").get_text(" ", strip=True)


def fetch_feed(url: str, *, source_name: str) -> Iterable[RawItem]:
    with http_client() as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content
    parsed = feedparser.parse(data)
    for entry in parsed.entries:
        link = entry.get("link") or ""
        guid = entry.get("id") or link or entry.get("title", "")
        ext_id = f"rss::{source_name}::{hashlib.sha1(guid.encode('utf-8')).hexdigest()[:16]}"
        summary = _strip_html(entry.get("summary") or entry.get("description"))
        content = None
        contents = entry.get("content")
        if contents:
            try:
                content = _strip_html(contents[0].get("value"))
            except (AttributeError, IndexError):
                content = None
        yield RawItem(
            external_id=ext_id,
            url=link,
            title=(entry.get("title") or "").strip(),
            summary=summary,
            content=content,
            author=entry.get("author"),
            published_at=_parse_date(entry),
            tags=["rss"],
        )
