from datetime import datetime, timedelta

from intel.storage.repo import (
    add_analysis,
    news_for_ticker,
    news_without_analysis,
    recent_news,
    search_news,
    upsert_company,
    upsert_news,
    upsert_quote,
)


def test_upsert_news_is_idempotent(session):
    company = upsert_company(session, ticker="NVDA", name="NVIDIA", exchange="NASDAQ", private=False, tags=["ai-chip"])
    assert company.id is not None

    payload = dict(
        source_id=None,
        external_id="rss::test::1",
        url="https://x/1",
        title="Blackwell B200 ramp",
        summary="NVIDIA scales Blackwell.",
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=["rss"],
        tickers=["NVDA"],
    )
    n1, created1 = upsert_news(session, **payload)
    n2, created2 = upsert_news(session, **payload)
    assert created1 is True
    assert created2 is False
    assert n1.id == n2.id


def test_recent_news_filter(session):
    upsert_news(
        session,
        source_id=None,
        external_id="ext::old",
        url="https://x/old",
        title="Old story",
        summary=None,
        content=None,
        author=None,
        published_at=datetime.utcnow() - timedelta(days=10),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=None,
    )
    upsert_news(
        session,
        source_id=None,
        external_id="ext::new",
        url="https://x/new",
        title="Fresh story",
        summary=None,
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=None,
    )
    items = recent_news(session, since=datetime.utcnow() - timedelta(hours=1))
    titles = [n.title for n in items]
    assert "Fresh story" in titles
    assert "Old story" not in titles


def test_news_without_analysis(session):
    n, _ = upsert_news(
        session,
        source_id=None,
        external_id="ext::a",
        url="https://x/a",
        title="Pending",
        summary=None,
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang=None,
        tags=None,
        tickers=None,
    )
    pending = news_without_analysis(session)
    assert any(p.id == n.id for p in pending)
    add_analysis(session, news_id=n.id, model="haiku", summary_zh="ok", impact="low")
    pending2 = news_without_analysis(session)
    assert all(p.id != n.id for p in pending2)


def test_search_news_ilike(session):
    upsert_news(
        session,
        source_id=None,
        external_id="ext::s1",
        url="https://x/s1",
        title="OpenAI ships GPT-9",
        summary=None,
        content="reasoning model launch",
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=["OPENAI"],
    )
    rows = search_news(session, "gpt-9")
    assert len(rows) == 1
    assert rows[0].title.startswith("OpenAI")


def test_news_for_ticker(session):
    upsert_news(
        session,
        source_id=None,
        external_id="ext::t1",
        url="https://x/t1",
        title="NVDA earnings",
        summary=None,
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=["NVDA", "AMD"],
    )
    upsert_news(
        session,
        source_id=None,
        external_id="ext::t2",
        url="https://x/t2",
        title="TSLA robotaxi",
        summary=None,
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=["TSLA"],
    )
    nvda = news_for_ticker(session, "NVDA")
    assert len(nvda) == 1
    assert "NVDA" in (nvda[0].tickers or [])


def test_upsert_quote_idempotent(session):
    company = upsert_company(session, ticker="AMD", name="AMD", exchange="NASDAQ", private=False, tags=None)
    d = datetime(2026, 5, 1)
    upsert_quote(session, company_id=company.id, date=d, open=100.0, high=110.0, low=99.0, close=108.0, volume=1.0)
    upsert_quote(session, company_id=company.id, date=d, open=100.0, high=111.0, low=99.0, close=109.0, volume=2.0)
    session.commit()
    rows = company.quotes
    assert len(rows) == 1
    assert rows[0].close == 109.0
