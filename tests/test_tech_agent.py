from datetime import datetime, timedelta

from intel.agents.tech_agent import build_user_message, gather_context, run_tech_agent
from intel.storage.repo import upsert_company, upsert_quote
from tests.test_agents import FakeClient


def _seed_prices(session, ticker, n, start=100.0, step=1.0):
    c = upsert_company(session, ticker=ticker, name=ticker, exchange="NASDAQ", private=False, tags=None)
    now = datetime.utcnow()
    for i in range(n):
        upsert_quote(
            session,
            company_id=c.id,
            date=now - timedelta(days=n - 1 - i),
            open=start + i * step,
            high=start + i * step + 0.5,
            low=start + i * step - 0.5,
            close=start + i * step,
            volume=1.0,
        )
    return c


def test_gather_context_no_data(session):
    ctx = gather_context(session, ticker="UNKNOWN", days=60)
    assert ctx["closes"] == []
    assert ctx["summary"]["n"] == 0


def test_gather_context_indicator_pipeline(session):
    _seed_prices(session, "NVDA", n=70, start=100.0, step=1.0)
    ctx = gather_context(session, ticker="NVDA", days=120)
    s = ctx["summary"]
    assert s["n"] == 70
    assert s["last"] == 169.0
    assert s["ma5"] is not None
    assert s["mom_20d"] is not None
    assert s["rsi14"] == 100.0  # monotonic


def test_user_message_contains_indicators(session):
    _seed_prices(session, "AMD", n=30)
    ctx = gather_context(session, ticker="AMD", days=60)
    msg = build_user_message(ctx)
    assert "AMD" in msg
    assert "RSI" in msg
    assert "MA5" in msg


def test_run_tech_agent_overlays_deterministic_indicators(session):
    _seed_prices(session, "META", n=70)
    fake = FakeClient(
        '```json\n{"tech_view":"bullish","key_levels":{"support":150,"resistance":180},'
        '"indicators":{"ma5":999,"made_up":true},"rationale":"x"}\n```\n中文正文。'
    )
    out = run_tech_agent(session, ticker="META", client=fake)
    # Deterministic indicators must overwrite anything the model invented.
    assert out.output_json["ticker"] == "META"
    assert out.output_json["indicators"]["n"] == 70
    assert out.output_json["indicators"]["ma5"] != 999  # we replaced it
    assert "made_up" not in out.output_json["indicators"]
    # The structural model output we kept (tech_view, key_levels) is intact.
    assert out.output_json["tech_view"] == "bullish"
