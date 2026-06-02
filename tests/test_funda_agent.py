from datetime import datetime, timedelta

from intel.agents.funda_agent import build_user_message, gather_context, run_funda_agent
from intel.storage.repo import upsert_company, upsert_filing, upsert_quote

# reuse the fake client from test_agents
from tests.test_agents import FakeClient


def test_gather_context_unknown_ticker(session):
    ctx = gather_context(session, ticker="UNKNOWN", days=30)
    assert ctx["ticker"] == "UNKNOWN"
    assert ctx["filings"] == []
    assert ctx["price"] is None


def test_gather_context_aggregates_price(session):
    c = upsert_company(session, ticker="NVDA", name="NVIDIA", exchange="NASDAQ", private=False, tags=["ai-chip"])
    now = datetime.utcnow()
    for i in range(5):
        upsert_quote(
            session,
            company_id=c.id,
            date=now - timedelta(days=4 - i),
            open=100.0 + i,
            high=110.0 + i,
            low=99.0 + i,
            close=105.0 + i,
            volume=1.0,
        )
    upsert_filing(
        session,
        company_id=c.id,
        accession="X-1",
        form="10-Q",
        filed_at=now - timedelta(days=10),
        url="https://sec/q",
        title="10-Q",
    )
    ctx = gather_context(session, ticker="NVDA", days=30)
    assert ctx["price"]["n_days"] == 5
    assert ctx["price"]["first_close"] == 105.0
    assert ctx["price"]["last_close"] == 109.0
    assert ctx["price"]["return_pct"] > 0
    assert any(f["form"] == "10-Q" for f in ctx["filings"])


def test_user_message_handles_private_company(session):
    upsert_company(session, ticker="OPENAI", name="OpenAI", exchange=None, private=True, tags=["lab"])
    ctx = gather_context(session, ticker="OPENAI", days=30)
    msg = build_user_message(ctx, days=30)
    assert "OPENAI" in msg
    assert "未上市" in msg
    assert "无 SEC 备案" in msg


def test_run_funda_agent_end_to_end(session):
    c = upsert_company(session, ticker="AMD", name="AMD", exchange="NASDAQ", private=False, tags=None)
    upsert_filing(
        session,
        company_id=c.id,
        accession="acc-1",
        form="10-K",
        filed_at=datetime.utcnow() - timedelta(days=60),
        url="https://sec/k",
        title="10-K",
    )
    fake = FakeClient(
        '```json\n{"ticker":"AMD","narrative_score":"neutral","valuation_signals":["P/S 较高"],"recent_filings":[],"key_metrics":{}}\n```\nAMD 基本面观察。'
    )
    out = run_funda_agent(session, ticker="AMD", days=30, client=fake)
    assert out.role == "funda"
    assert out.output_json["ticker"] == "AMD"
    assert out.output_json["narrative_score"] == "neutral"
    # the agent's system prompt mentions 基本面分析师
    call = fake.messages.calls[0]
    assert "基本面分析师" in call["system"][0]["text"]
