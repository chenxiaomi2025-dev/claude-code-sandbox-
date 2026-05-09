"""Repository helpers: idempotent upserts and common queries."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from intel.storage.models import Analysis, Company, Digest, Filing, NewsItem, Quote, Source


def upsert_company(session: Session, **fields) -> Company:
    ticker = fields["ticker"]
    obj = session.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
    if obj is None:
        obj = Company(**fields)
        session.add(obj)
        session.flush()
    else:
        for k, v in fields.items():
            setattr(obj, k, v)
    return obj


def upsert_source(session: Session, *, kind: str, name: str, url: str | None, weight: int) -> Source:
    obj = session.execute(
        select(Source).where(Source.kind == kind, Source.name == name)
    ).scalar_one_or_none()
    if obj is None:
        obj = Source(kind=kind, name=name, url=url, weight=weight)
        session.add(obj)
        session.flush()
    else:
        obj.url = url
        obj.weight = weight
    return obj


def upsert_news(session: Session, **fields) -> tuple[NewsItem, bool]:
    """Return (news, created)."""
    ext = fields["external_id"]
    obj = session.execute(select(NewsItem).where(NewsItem.external_id == ext)).scalar_one_or_none()
    if obj is None:
        obj = NewsItem(**fields)
        session.add(obj)
        session.flush()
        return obj, True
    return obj, False


def upsert_quote(session: Session, *, company_id: int, date: datetime, **prices) -> Quote:
    obj = session.execute(
        select(Quote).where(Quote.company_id == company_id, Quote.date == date)
    ).scalar_one_or_none()
    if obj is None:
        obj = Quote(company_id=company_id, date=date, **prices)
        session.add(obj)
    else:
        for k, v in prices.items():
            setattr(obj, k, v)
    return obj


def upsert_filing(session: Session, **fields) -> tuple[Filing, bool]:
    accession = fields["accession"]
    obj = session.execute(select(Filing).where(Filing.accession == accession)).scalar_one_or_none()
    if obj is None:
        obj = Filing(**fields)
        session.add(obj)
        return obj, True
    return obj, False


def recent_news(session: Session, *, since: datetime, limit: int = 200) -> list[NewsItem]:
    stmt = (
        select(NewsItem)
        .where(NewsItem.published_at.is_not(None), NewsItem.published_at >= since)
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def news_without_analysis(session: Session, *, limit: int = 50) -> list[NewsItem]:
    sub = select(Analysis.news_id)
    stmt = (
        select(NewsItem)
        .where(NewsItem.id.not_in(sub))
        .order_by(NewsItem.fetched_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def search_news(session: Session, query: str, limit: int = 50) -> list[NewsItem]:
    like = f"%{query}%"
    stmt = (
        select(NewsItem)
        .where((NewsItem.title.ilike(like)) | (NewsItem.summary.ilike(like)) | (NewsItem.content.ilike(like)))
        .order_by(NewsItem.published_at.desc().nulls_last())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def news_for_ticker(session: Session, ticker: str, days: int = 14, limit: int = 100) -> list[NewsItem]:
    since = datetime.utcnow() - timedelta(days=days)
    stmt = (
        select(NewsItem)
        .where(NewsItem.fetched_at >= since)
        .order_by(NewsItem.published_at.desc().nulls_last())
        .limit(limit * 4)
    )
    rows = list(session.execute(stmt).scalars())
    out: list[NewsItem] = []
    for r in rows:
        tickers = r.tickers or []
        if ticker in tickers:
            out.append(r)
        if len(out) >= limit:
            break
    return out


def add_analysis(session: Session, **fields) -> Analysis:
    obj = Analysis(**fields)
    session.add(obj)
    session.flush()
    return obj


def add_digest(session: Session, **fields) -> Digest:
    obj = Digest(**fields)
    session.add(obj)
    session.flush()
    return obj


def get_company(session: Session, ticker: str) -> Company | None:
    return session.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()


def all_companies(session: Session) -> list[Company]:
    return list(session.execute(select(Company)).scalars())
