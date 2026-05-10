"""Orchestrates collectors: walks the source config, persists items idempotently."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from intel.collectors import arxiv as arxiv_mod
from intel.collectors import earnings as earnings_mod
from intel.collectors import hackernews as hn_mod
from intel.collectors import quotes as quotes_mod
from intel.collectors import rss as rss_mod
from intel.collectors import sec_edgar as edgar_mod
from intel.collectors.base import tag_tickers
from intel.config.loader import company_keywords, load_companies, load_sources
from intel.storage.db import init_db, session_scope
from intel.storage.repo import (
    upsert_company,
    upsert_earnings_event,
    upsert_filing,
    upsert_news,
    upsert_quote,
    upsert_source,
)

log = logging.getLogger("intel.collect")


@dataclass
class CollectStats:
    fetched: int = 0
    new: int = 0
    failed: int = 0


def _persist_news_items(session, source, items, kw_index):
    stats = CollectStats()
    for raw in items:
        stats.fetched += 1
        try:
            text = " ".join(filter(None, [raw.title, raw.summary, raw.content]))
            tickers = tag_tickers(text, kw_index)
            _, created = upsert_news(
                session,
                source_id=source.id,
                external_id=raw.external_id,
                url=raw.url,
                title=raw.title[:500],
                summary=raw.summary,
                content=raw.content,
                author=raw.author,
                published_at=raw.published_at,
                fetched_at=datetime.utcnow(),
                lang=raw.lang,
                tags=raw.tags or None,
                tickers=tickers or None,
            )
            if created:
                stats.new += 1
        except Exception as e:  # pragma: no cover - defensive
            stats.failed += 1
            log.warning("persist failed: %s", e)
    return stats


def collect_all(*, kinds: tuple[str, ...] | None = None) -> dict[str, CollectStats]:
    """Run every collector listed in sources.yaml. Returns stats per source."""
    init_db()
    sources_cfg = load_sources()
    kw_index = company_keywords()
    results: dict[str, CollectStats] = {}

    with session_scope() as session:
        # Make sure companies exist in DB.
        for c in load_companies():
            upsert_company(
                session,
                ticker=c["ticker"],
                name=c["name"],
                exchange=c.get("exchange"),
                cik=c.get("cik"),
                private=bool(c.get("private", False)),
                tags=c.get("tags"),
            )

        if not kinds or "rss" in kinds:
            for cfg in sources_cfg.get("rss", []):
                src = upsert_source(session, kind="rss", name=cfg["name"], url=cfg["url"], weight=cfg.get("weight", 5))
                try:
                    items = list(rss_mod.fetch_feed(cfg["url"], source_name=cfg["name"]))
                except Exception as e:
                    log.warning("rss %s failed: %s", cfg["name"], e)
                    results[f"rss::{cfg['name']}"] = CollectStats(failed=1)
                    continue
                results[f"rss::{cfg['name']}"] = _persist_news_items(session, src, items, kw_index)
                src.last_fetched_at = datetime.utcnow()

        if not kinds or "arxiv" in kinds:
            for cfg in sources_cfg.get("arxiv", []):
                src = upsert_source(session, kind="arxiv", name=cfg["name"], url=None, weight=cfg.get("weight", 5))
                try:
                    items = list(arxiv_mod.fetch_arxiv(cfg["category"], max_results=40))
                except Exception as e:
                    log.warning("arxiv %s failed: %s", cfg["name"], e)
                    results[f"arxiv::{cfg['name']}"] = CollectStats(failed=1)
                    continue
                results[f"arxiv::{cfg['name']}"] = _persist_news_items(session, src, items, kw_index)
                src.last_fetched_at = datetime.utcnow()

        if not kinds or "hackernews" in kinds:
            for cfg in sources_cfg.get("hackernews", []):
                src = upsert_source(session, kind="hackernews", name=cfg["name"], url=None, weight=cfg.get("weight", 5))
                try:
                    items = list(hn_mod.fetch_hn(min_points=cfg.get("min_points", 200)))
                except Exception as e:
                    log.warning("hn failed: %s", e)
                    results[f"hn::{cfg['name']}"] = CollectStats(failed=1)
                    continue
                results[f"hn::{cfg['name']}"] = _persist_news_items(session, src, items, kw_index)
                src.last_fetched_at = datetime.utcnow()

        if not kinds or "sec_edgar" in kinds:
            stats = CollectStats()
            for c in load_companies():
                cik = c.get("cik")
                if not cik:
                    continue
                company = upsert_company(
                    session,
                    ticker=c["ticker"],
                    name=c["name"],
                    exchange=c.get("exchange"),
                    cik=cik,
                    private=False,
                    tags=c.get("tags"),
                )
                try:
                    for f in edgar_mod.fetch_filings(cik):
                        stats.fetched += 1
                        _, created = upsert_filing(
                            session,
                            company_id=company.id,
                            accession=f["accession"],
                            form=f["form"],
                            filed_at=f["filed_at"],
                            url=f["url"],
                            title=f["title"],
                        )
                        if created:
                            stats.new += 1
                except Exception as e:
                    log.warning("edgar %s failed: %s", c["ticker"], e)
                    stats.failed += 1
            results["sec_edgar"] = stats

        if kinds and "earnings" in kinds:
            stats = CollectStats()
            for c in load_companies():
                if c.get("private"):
                    continue
                company = upsert_company(
                    session,
                    ticker=c["ticker"],
                    name=c["name"],
                    exchange=c.get("exchange"),
                    cik=c.get("cik"),
                    private=False,
                    tags=c.get("tags"),
                )
                try:
                    dates = earnings_mod.fetch_earnings(c["ticker"])
                except Exception as e:
                    log.warning("earnings %s failed: %s", c["ticker"], e)
                    stats.failed += 1
                    continue
                for d in dates:
                    stats.fetched += 1
                    upsert_earnings_event(session, company_id=company.id, expected_date=d)
                    stats.new += 1
            results["earnings"] = stats

        if kinds and "yfinance" in kinds:
            stats = CollectStats()
            for c in load_companies():
                if c.get("private"):
                    continue
                company = upsert_company(
                    session,
                    ticker=c["ticker"],
                    name=c["name"],
                    exchange=c.get("exchange"),
                    cik=c.get("cik"),
                    private=False,
                    tags=c.get("tags"),
                )
                try:
                    for q in quotes_mod.fetch_prices(c["ticker"], period="1mo"):
                        stats.fetched += 1
                        upsert_quote(session, company_id=company.id, **q)
                        stats.new += 1
                except Exception as e:
                    log.warning("yfinance %s failed: %s", c["ticker"], e)
                    stats.failed += 1
            results["yfinance"] = stats

    return results
