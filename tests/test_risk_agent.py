from datetime import datetime, timedelta

from intel.agents.risk_agent import build_user_message, gather_context, run_risk_agent
from intel.storage.repo import (
    add_analysis,
    upsert_company,
    upsert_earnings_event,
    upsert_filing,
    upsert_news,
    upsert_quote,
)
from tests.test_agents import FakeClient


def test_gather_unknown_ticker(session):
    ctx = gather_context(session, ticker="UNKNOWN", hours=48)
    assert ctx["alerts"] == []
    assert ctx["drawdown_pct"] is None


def test_gather_pulls_relevant_alerts_only(session):
    c1 = upsert_company(session, ticker="NVDA", name="NVIDIA", exchange="NASDAQ", private=False, tags=["ai-chip"])
    c2 = upsert_company(session, ticker="AMD", name="AMD", exchange="NASDAQ", private=False, tags=None)
    # NVDA filing → earnings alert for NVDA
    upsert_filing(
        session,
        company_id=c1.id,
        accession="acc-nvda",
        form="10-Q",
        filed_at=datetime.utcnow() - timedelta(hours=2),
        url="https://sec/nvda",
        title="10-Q",
    )
    # AMD-only news with regulation keyword → AMD alert
    upsert_news(
        session,
        source_id=None,
        external_id="ext::amd-reg",
        url="https://x/amd",
        title="EU launches antitrust investigation of AMD chiplet practices",
        summary=None,
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=["AMD"],
    )
    _ = c2  # ensure AMD created
    ctx = gather_context(session, ticker="NVDA", hours=48)
    assert all(a["kind"] != "regulation" or "AMD" not in a["title"] for a in ctx["alerts"])
    assert any(a["kind"] == "earnings" for a in ctx["alerts"])


def test_gather_detects_near_earnings(session):
    c = upsert_company(session, ticker="MSFT", name="Microsoft", exchange="NASDAQ", private=False, tags=None)
    upsert_earnings_event(session, company_id=c.id, expected_date=datetime.utcnow() + timedelta(days=2))
    ctx = gather_context(session, ticker="MSFT", hours=24)
    assert ctx["earnings"] == [2] or ctx["earnings"][0] in (1, 2)


def test_gather_computes_drawdown(session):
    c = upsert_company(session, ticker="TSLA", name="Tesla", exchange="NASDAQ", private=False, tags=None)
    base = datetime.utcnow()
    # rises then drops
    series = [100, 120, 150, 140, 110, 100, 95]
    for i, p in enumerate(series):
        upsert_quote(
            session, company_id=c.id, date=base - timedelta(days=len(series) - 1 - i),
            open=p, high=p, low=p, close=float(p), volume=1.0,
        )
    ctx = gather_context(session, ticker="TSLA", hours=24)
    # peak 150, last 95 → -36.67%
    assert ctx["drawdown_pct"] is not None
    assert ctx["drawdown_pct"] < -30


def test_user_message_shape(session):
    c = upsert_company(session, ticker="META", name="Meta", exchange="NASDAQ", private=False, tags=["ar"])
    upsert_filing(
        session, company_id=c.id, accession="meta-1", form="10-K",
        filed_at=datetime.utcnow(), url="https://sec/meta", title="10-K",
    )
    ctx = gather_context(session, ticker="META", hours=24)
    msg = build_user_message(ctx)
    assert "META" in msg
    assert "相关告警" in msg
    assert "回撤" in msg


def test_run_risk_agent_overlays_counts(session):
    c = upsert_company(session, ticker="GOOGL", name="Alphabet", exchange="NASDAQ", private=False, tags=None)
    upsert_earnings_event(session, company_id=c.id, expected_date=datetime.utcnow() + timedelta(days=1))
    fake = FakeClient(
        '```json\n{"overall_risk":"high","near_earnings":false,"open_alerts":42,"top_risks":[{"category":"reg","detail":"x"}],"rationale":"y"}\n```\n中文风险说明。'
    )
    out = run_risk_agent(session, ticker="GOOGL", hours=48, client=fake)
    # Deterministic counts must overwrite hallucinated ones
    assert out.output_json["near_earnings"] is True
    # open_alerts comes from real alerts engine count, not the model's "42"
    assert out.output_json["open_alerts"] != 42
    # Model-supplied fields preserved
    assert out.output_json["overall_risk"] == "high"


def test_add_analysis_call_ok_for_test_dependencies(session):
    """sanity: ensure add_analysis is importable (used elsewhere in suite)"""
    n, _ = upsert_news(
        session, source_id=None, external_id="ext::sanity", url="https://x", title="t",
        summary=None, content=None, author=None,
        published_at=datetime.utcnow(), fetched_at=datetime.utcnow(),
        lang=None, tags=None, tickers=None,
    )
    add_analysis(session, news_id=n.id, model="haiku", summary_zh="x", impact="low")
