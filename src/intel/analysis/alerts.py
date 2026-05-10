"""Event alert detector.

Scans recently analyzed news + filings and emits structured Alert objects for
events that an investor should not miss:

  - HIGH_IMPACT  : analysis.impact == 'high'
  - EARNINGS     : 10-K / 10-Q filing OR earnings keywords in news
  - REGULATION   : keywords like "antitrust", "subpoena", "investigation",
                   "出口管制", "反垄断" ...
  - EXEC_CHANGE  : "CEO", "steps down", "resigns", "leadership change",
                   "高管", "辞职" ...
  - FUNDRAISE    : "raised", "Series", "valuation", "融资", "估值"
  - PRODUCT      : "launches", "unveils", "announces", "release", "发布"

Pure rules engine — no LLM call. Alerts are sorted by severity then time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from intel.storage.models import Analysis, Company, EarningsEvent, Filing, NewsItem


@dataclass
class Alert:
    severity: str  # critical | high | medium | low
    kind: str  # high_impact | earnings | regulation | exec_change | fundraise | product
    title: str
    url: str
    tickers: list[str]
    when: datetime
    rationale: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "tickers": list(self.tickers),
            "when": self.when.isoformat(),
            "rationale": self.rationale,
        }


_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# Trigger keywords. We accept both English and Chinese phrasing.
KEYWORDS = {
    "regulation": [
        "antitrust", "subpoena", "investigation", "lawsuit", "fine ", "ban",
        "export control", "sanction",
        "反垄断", "出口管制", "调查", "处罚", "起诉", "禁售",
    ],
    "exec_change": [
        "ceo", "steps down", "resigns", "resigned", "departs", "fired",
        "leadership change", "appointed",
        "辞职", "离任", "卸任", "履新", "任命", "高管变动",
    ],
    "earnings": [
        "earnings", "revenue beat", "revenue miss", "quarterly results",
        "guidance",
        "财报", "营收", "净利润", "业绩指引",
    ],
    "fundraise": [
        "raised", "series ", "valuation of", "funding round", "ipo",
        "融资", "估值", "上市",
    ],
    "product": [
        "launches", "unveils", "announces", "release of", "introduces",
        "发布", "推出", "上线",
    ],
}


def _match_kind(text: str) -> str | None:
    if not text:
        return None
    haystack = text.lower()
    # priority order: regulation > exec_change > earnings > fundraise > product
    for kind in ("regulation", "exec_change", "earnings", "fundraise", "product"):
        for kw in KEYWORDS[kind]:
            if kw in haystack:
                return kind
    return None


def _severity(kind: str, *, llm_impact: str | None = None) -> str:
    if llm_impact == "high":
        return "high"
    return {
        "regulation": "high",
        "exec_change": "medium",
        "earnings": "high",
        "fundraise": "medium",
        "product": "medium",
        "high_impact": "high",
    }.get(kind, "low")


def detect_alerts(
    session: Session,
    *,
    hours: int = 48,
    earnings_lookahead_days: int = 7,
) -> list[Alert]:
    """Return alerts derived from the last `hours` of news + filings, plus any
    upcoming earnings dates within `earnings_lookahead_days`.

    Earnings filings (10-K / 10-Q) always become alerts. News items become
    alerts when (a) keywords match a kind, or (b) the latest analysis flagged
    them as high impact. Forward-looking earnings dates are emitted as their
    own 'earnings_upcoming' alerts so users see them in the daily digest.
    """
    since = datetime.utcnow() - timedelta(hours=hours)
    out: list[Alert] = []

    # 0) Upcoming earnings within the lookahead window
    now = datetime.utcnow()
    horizon = now + timedelta(days=earnings_lookahead_days)
    upcoming = list(
        session.execute(
            select(EarningsEvent, Company)
            .join(Company, EarningsEvent.company_id == Company.id)
            .where(EarningsEvent.expected_date >= now, EarningsEvent.expected_date <= horizon)
            .order_by(EarningsEvent.expected_date.asc())
        ).all()
    )
    for event, company in upcoming:
        days = max(0, (event.expected_date - now).days)
        sev = "high" if days <= 2 else "medium"
        out.append(
            Alert(
                severity=sev,
                kind="earnings_upcoming",
                title=f"{company.ticker} 财报日:{event.expected_date.strftime('%Y-%m-%d')} (T-{days}d)",
                url="",
                tickers=[company.ticker],
                when=event.expected_date,
                rationale=f"距离财报 {days} 天",
            )
        )

    # 1) SEC filings — 10-K / 10-Q / 8-K are always interesting
    filings = list(
        session.execute(
            select(Filing).where(Filing.filed_at >= since).order_by(Filing.filed_at.desc())
        ).scalars()
    )
    for f in filings:
        out.append(
            Alert(
                severity="high" if f.form in ("10-K", "10-Q", "8-K") else "medium",
                kind="earnings" if f.form in ("10-K", "10-Q") else "regulation",
                title=f"{f.company.ticker} 提交 {f.form}",
                url=f.url,
                tickers=[f.company.ticker],
                when=f.filed_at,
                rationale=f"SEC 备案 {f.form}",
            )
        )

    # 2) News — keyword + impact-driven
    news_items = list(
        session.execute(
            select(NewsItem)
            .where(NewsItem.fetched_at >= since)
            .order_by(NewsItem.published_at.desc().nulls_last())
        ).scalars()
    )
    for n in news_items:
        text = " ".join(filter(None, [n.title, n.summary, n.content]))
        latest_analysis: Analysis | None = max(n.analyses, key=lambda a: a.created_at) if n.analyses else None
        impact = (latest_analysis.impact if latest_analysis else None) or None
        kind = _match_kind(text)

        if not kind and impact != "high":
            continue
        # high-impact analyses without keyword match still surface as 'high_impact'
        kind = kind or "high_impact"
        sev = _severity(kind, llm_impact=impact)
        rationale_parts = []
        if kind != "high_impact":
            rationale_parts.append(f"关键字命中:{kind}")
        if impact:
            rationale_parts.append(f"LLM 影响等级:{impact}")
        out.append(
            Alert(
                severity=sev,
                kind=kind,
                title=n.title,
                url=n.url,
                tickers=list(n.tickers or []),
                when=n.published_at or n.fetched_at,
                rationale="; ".join(rationale_parts) or "高影响事件",
            )
        )

    def _sort_key(a: Alert):
        rank = _SEVERITY_RANK.get(a.severity, 9)
        # Within a severity bucket, list upcoming earnings ascending (soonest
        # first) and past events descending (newest first).
        if a.kind == "earnings_upcoming":
            return (rank, 0, a.when.timestamp())
        return (rank, 1, -a.when.timestamp())

    out.sort(key=_sort_key)
    return out
