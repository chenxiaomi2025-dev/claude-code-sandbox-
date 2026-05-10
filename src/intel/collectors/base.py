"""Shared collector primitives: HTTP client, ticker tagging, dataclasses."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from intel.config.loader import company_keywords
from intel.config.settings import settings


@dataclass
class RawItem:
    external_id: str
    url: str
    title: str
    summary: str | None = None
    content: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    lang: str | None = None
    tags: list[str] = field(default_factory=list)


def http_client() -> httpx.Client:
    return httpx.Client(
        timeout=settings.http_timeout,
        headers={"User-Agent": settings.http_ua, "Accept": "*/*"},
        follow_redirects=True,
    )


def _has_cjk(s: str) -> bool:
    return any("一" <= c <= "鿿" for c in s)


def tag_tickers(text: str, tickers_keywords: dict[str, list[str]] | None = None) -> list[str]:
    """Best-effort keyword match of company names/tickers/aliases in `text`.

    Min-length filter: ASCII keywords need >2 chars to avoid false positives;
    CJK keywords need only >=2 chars (Chinese names are dense — "阿里" / "腾讯"
    are unambiguous).
    """
    if not text:
        return []
    haystack = text.lower()
    keywords = tickers_keywords or company_keywords()
    found: list[str] = []
    for ticker, names in keywords.items():
        for n in names:
            if not n:
                continue
            needle = n.lower()
            min_len = 2 if _has_cjk(needle) else 3
            if len(needle) < min_len:
                continue
            if needle in haystack:
                found.append(ticker)
                break
    return sorted(set(found))


def chunk(items: Iterable, size: int):
    bucket: list = []
    for it in items:
        bucket.append(it)
        if len(bucket) == size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket
