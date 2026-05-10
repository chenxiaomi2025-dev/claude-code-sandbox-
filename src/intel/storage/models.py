"""SQLAlchemy ORM models for the intelligence database."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cik: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    private: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    quotes: Mapped[list[Quote]] = relationship(back_populates="company", cascade="all, delete-orphan")
    filings: Mapped[list[Filing]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # rss/arxiv/hackernews/sec_edgar/yfinance
    name: Mapped[str] = mapped_column(String(128))
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    weight: Mapped[int] = mapped_column(Integer, default=5)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("kind", "name", name="uq_source_kind_name"),)


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True, index=True)
    external_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    lang: Mapped[str | None] = mapped_column(String(8), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    tickers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    analyses: Mapped[list[Analysis]] = relationship(back_populates="news", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_news_published_desc", "published_at"),
    )


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_items.id"), index=True)
    model: Mapped[str] = mapped_column(String(64))
    summary_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact: Mapped[str | None] = mapped_column(String(16), nullable=True)  # high/medium/low
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)  # -1..1
    affected_tickers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    themes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    news: Mapped[NewsItem] = relationship(back_populates="analyses")


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)

    company: Mapped[Company] = relationship(back_populates="quotes")

    __table_args__ = (UniqueConstraint("company_id", "date", name="uq_quote_company_date"),)


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    accession: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    form: Mapped[str] = mapped_column(String(16))  # 10-K, 10-Q, 8-K, S-1...
    filed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    company: Mapped[Company] = relationship(back_populates="filings")


class EarningsEvent(Base):
    __tablename__ = "earnings_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    expected_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String(32), default="yfinance")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("company_id", "expected_date", name="uq_earnings_company_date"),
    )


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[str] = mapped_column(String(16), index=True)  # daily/weekly
    range_start: Mapped[datetime] = mapped_column(DateTime)
    range_end: Mapped[datetime] = mapped_column(DateTime)
    model: Mapped[str] = mapped_column(String(64))
    body_md: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
