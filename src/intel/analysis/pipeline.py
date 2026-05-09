"""Analysis orchestration: fetch un-analyzed news, call Claude, persist results."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from intel.analysis.llm import analyze_news, synthesize_digest
from intel.config.settings import settings
from intel.storage.db import init_db, session_scope
from intel.storage.repo import (
    add_analysis,
    add_digest,
    news_without_analysis,
    recent_news,
)

log = logging.getLogger("intel.analysis")

_DIRECTION_TO_SENTIMENT = {"positive": 0.6, "negative": -0.6, "neutral": 0.0}


def analyze_pending(*, limit: int = 30, model: str | None = None) -> int:
    init_db()
    done = 0
    with session_scope() as session:
        items = news_without_analysis(session, limit=limit)
        for item in items:
            body = item.content or item.summary or ""
            try:
                result = analyze_news(title=item.title, body=body, model=model)
            except Exception as e:
                log.warning("analyze failed for news %s: %s", item.id, e)
                continue
            add_analysis(
                session,
                news_id=item.id,
                model=model or settings.model_fast,
                summary_zh=result.get("summary_zh"),
                impact=(result.get("impact") or "low").lower(),
                sentiment=_DIRECTION_TO_SENTIMENT.get((result.get("direction") or "neutral").lower(), 0.0),
                affected_tickers=result.get("affected_tickers") or [],
                themes=result.get("themes") or [],
                rationale=result.get("rationale"),
            )
            done += 1
    return done


def build_digest(*, hours: int = 24, model: str | None = None, period: str = "daily") -> str:
    init_db()
    since = datetime.utcnow() - timedelta(hours=hours)
    with session_scope() as session:
        news_items = recent_news(session, since=since, limit=300)
        payload = []
        for n in news_items:
            latest = max(n.analyses, key=lambda a: a.created_at) if n.analyses else None
            if not latest:
                continue
            payload.append(
                {
                    "title": n.title,
                    "url": n.url,
                    "summary_zh": latest.summary_zh,
                    "impact": latest.impact,
                    "affected_tickers": latest.affected_tickers,
                    "themes": latest.themes,
                }
            )
        # rank: high > medium > low, then has tickers
        order = {"high": 0, "medium": 1, "low": 2}
        payload.sort(key=lambda x: (order.get(x.get("impact", "low"), 3), -len(x.get("affected_tickers") or [])))
        if not payload:
            return "_最近窗口内没有已分析的情报,请先运行 `intel collect` 与 `intel analyze`。_"
        body_md = synthesize_digest(items=payload, model=model, period=period)
        add_digest(
            session,
            period=period,
            range_start=since,
            range_end=datetime.utcnow(),
            model=model or settings.model_deep,
            body_md=body_md,
        )
        return body_md
