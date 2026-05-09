"""Shared collector primitives: HTTP client, ticker tagging, dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

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


def tag_tickers(text: str, tickers_keywords: dict[str, list[str]] | None = None) -> list[str]:
    """Best-effort keyword match of company names/tickers in `text`."""
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
            if len(needle) <= 2:
                # avoid ultra-short tokens producing false positives
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
