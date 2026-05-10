from datetime import datetime, timedelta

from intel.analysis.alerts import _match_kind, detect_alerts
from intel.storage.repo import (
    add_analysis,
    upsert_company,
    upsert_filing,
    upsert_news,
)


def test_match_kind_priority():
    # regulation outranks product when both keywords present
    assert _match_kind("FTC launches antitrust investigation into NVDA") == "regulation"
    assert _match_kind("Apple unveils new chip") == "product"
    assert _match_kind("CEO steps down today") == "exec_change"
    assert _match_kind("Company raised Series E at valuation of $5B") == "fundraise"
    assert _match_kind("Quarterly earnings beat estimates") == "earnings"
    assert _match_kind("nothing relevant here") is None


def test_match_kind_chinese():
    assert _match_kind("百度被反垄断调查") == "regulation"
    assert _match_kind("CFO 离任") == "exec_change"
    assert _match_kind("月之暗面新一轮融资,估值翻倍") == "fundraise"


def test_detect_alerts_from_filing(session):
    company = upsert_company(session, ticker="NVDA", name="NVIDIA", exchange="NASDAQ", private=False, tags=None)
    upsert_filing(
        session,
        company_id=company.id,
        accession="0001045810-26-000001",
        form="10-Q",
        filed_at=datetime.utcnow() - timedelta(hours=1),
        url="https://sec/x",
        title="10-Q",
    )
    alerts = detect_alerts(session, hours=24)
    assert any(a.kind == "earnings" and "NVDA" in a.tickers for a in alerts)


def test_detect_alerts_from_high_impact(session):
    n, _ = upsert_news(
        session,
        source_id=None,
        external_id="ext::hi",
        url="https://x/hi",
        title="Mystery news without keywords",
        summary=None,
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=["TSLA"],
    )
    add_analysis(
        session,
        news_id=n.id,
        model="haiku",
        summary_zh="重大事件",
        impact="high",
        affected_tickers=["TSLA"],
    )
    alerts = detect_alerts(session, hours=24)
    assert any(a.kind == "high_impact" and "TSLA" in a.tickers for a in alerts)


def test_detect_alerts_keyword_news(session):
    upsert_news(
        session,
        source_id=None,
        external_id="ext::reg",
        url="https://x/reg",
        title="EU launches antitrust investigation into Google",
        summary=None,
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=["GOOGL"],
    )
    alerts = detect_alerts(session, hours=24)
    matching = [a for a in alerts if a.kind == "regulation"]
    assert len(matching) == 1
    assert matching[0].severity == "high"


def test_detect_alerts_sorted_by_severity(session):
    company = upsert_company(session, ticker="AMD", name="AMD", exchange="NASDAQ", private=False, tags=None)
    upsert_filing(
        session,
        company_id=company.id,
        accession="X-1",
        form="10-K",
        filed_at=datetime.utcnow(),
        url="https://sec/x1",
        title="10-K",
    )
    upsert_news(
        session,
        source_id=None,
        external_id="ext::p",
        url="https://x/p",
        title="AMD launches new GPU",
        summary=None,
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=["AMD"],
    )
    alerts = detect_alerts(session, hours=24)
    # earnings (high severity) should come before product (medium)
    severities = [a.severity for a in alerts]
    assert severities == sorted(severities, key=lambda s: {"high": 1, "medium": 2}.get(s, 9))
