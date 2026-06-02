"""End-to-end coordinator tests with a programmable FakeClient that returns
different responses for different system prompts (so each agent in the chain
gets a role-appropriate JSON payload)."""
from __future__ import annotations

from datetime import datetime, timedelta

from intel.agents.coordinator import render_report, run_decision
from intel.storage.repo import (
    recent_decisions,
    upsert_company,
    upsert_filing,
    upsert_news,
    upsert_quote,
)


# A multi-role fake client that picks a canned response based on the system prompt.
class RolledFakeClient:
    _RESPONSES = {
        "新闻分析师": (
            '```json\n{"ticker":"NVDA","window_days":14,"net_view":"bullish",'
            '"confidence":0.8,"catalysts":[{"date":"2026-05-01","title":"Blackwell ramp",'
            '"impact":"high","direction":"positive","summary":"x","url":"u"}]}\n```\n中文。'
        ),
        "基本面分析师": (
            '```json\n{"ticker":"NVDA","narrative_score":"strong",'
            '"valuation_signals":["P/E 高但 EPS 加速"],"recent_filings":[],"key_metrics":{}}\n```\n中文。'
        ),
        "技术分析师": (
            '```json\n{"ticker":"NVDA","tech_view":"bullish",'
            '"key_levels":{"support":150,"resistance":180},"rationale":"x"}\n```\n中文。'
        ),
        "风控分析师": (
            '```json\n{"ticker":"NVDA","overall_risk":"medium",'
            '"top_risks":[{"category":"reg","detail":"export control"}],"rationale":"y"}\n```\n中文。'
        ),
        "投资组合经理": (
            '```json\n{"ticker":"NVDA","decision":"buy","confidence":0.72,'
            '"horizon":"medium","thesis":"算力周期延续",'
            '"bull_points":["B300","盈利能力"],"bear_points":["估值偏高"],'
            '"key_risks":["监管"],"monitor":["FY26Q1 财报"]}\n```\nPM 备忘。'
        ),
    }

    class _Messages:
        def __init__(self, parent):
            self.parent = parent
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            sys_text = kwargs["system"][0]["text"]
            for needle, blob in RolledFakeClient._RESPONSES.items():
                if needle in sys_text:
                    return _FakeResp(blob)
            return _FakeResp('{"unknown_role": true}')

    def __init__(self):
        self.messages = self._Messages(self)


class _FakeBlock:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class _FakeUsage:
    input_tokens = 100
    output_tokens = 50
    cache_read_input_tokens = 10


class _FakeResp:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]
        self.usage = _FakeUsage()


# ---- tests ----

def _seed_ticker(session, ticker="NVDA"):
    c = upsert_company(session, ticker=ticker, name="NVIDIA", exchange="NASDAQ", private=False, tags=["ai-chip"])
    now = datetime.utcnow()
    for i in range(70):
        upsert_quote(
            session, company_id=c.id, date=now - timedelta(days=69 - i),
            open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.0 + i, volume=1.0,
        )
    upsert_news(
        session, source_id=None, external_id=f"ext::{ticker}",
        url="https://x/1", title=f"{ticker} ships new chip", summary=None, content=None,
        author=None, published_at=now, fetched_at=now,
        lang="en", tags=None, tickers=[ticker],
    )
    upsert_filing(
        session, company_id=c.id, accession="acc-1", form="10-Q",
        filed_at=now - timedelta(days=10), url="https://sec/q", title="10-Q",
    )
    return c


def test_run_decision_chains_all_5_agents(session):
    _seed_ticker(session)
    fake = RolledFakeClient()
    bundle = run_decision(session, ticker="NVDA", client=fake, persist=False)
    # Coordinator called Claude 5 times — once per agent
    assert len(fake.messages.calls) == 5
    # Each role's system prompt should appear exactly once
    seen = [c["system"][0]["text"] for c in fake.messages.calls]
    for needle in ("新闻分析师", "基本面分析师", "技术分析师", "风控分析师", "投资组合经理"):
        assert sum(needle in s for s in seen) == 1, f"missing role: {needle}"

    assert bundle.decision == "buy"
    assert bundle.confidence == 0.72
    assert bundle.horizon == "medium"
    assert "NVDA" in bundle.report_md
    assert "B300" in bundle.report_md or "盈利" in bundle.report_md


def test_run_decision_persists_to_db(session):
    _seed_ticker(session)
    fake = RolledFakeClient()
    bundle = run_decision(session, ticker="NVDA", client=fake, persist=True)
    assert bundle.db_id is not None
    rows = recent_decisions(session, ticker="NVDA")
    assert len(rows) == 1
    row = rows[0]
    assert row.ticker == "NVDA"
    assert row.decision == "buy"
    assert row.payload["pm"]["decision"] == "buy"
    assert "NVDA" in (row.report_md or "")


def test_run_decision_skips_persist_when_requested(session):
    _seed_ticker(session)
    fake = RolledFakeClient()
    bundle = run_decision(session, ticker="NVDA", client=fake, persist=False)
    assert bundle.db_id is None
    assert recent_decisions(session) == []


def test_render_report_handles_missing_fields():
    md = render_report(
        {"pm": {"decision": "hold"}, "news": {}, "funda": {}, "tech": {"indicators": {}}, "risk": {}},
        ticker="X",
    )
    assert "# X 投研决策" in md
    assert "HOLD" in md
    assert "_无_" in md  # empty bullet lists rendered as 无


def test_run_decision_runs_analysts_in_parallel(session):
    """Each analyst call sleeps 200ms in the fake. Sequential = 4 × 200 = 800ms;
    parallel should beat ~400ms easily (allow generous headroom for CI jitter)."""
    import time

    class _SlowMessages:
        def __init__(self):
            self.calls: list[dict] = []
            self.role_order: list[str] = []

        def create(self, **kwargs):
            sys_text = kwargs["system"][0]["text"]
            for role_marker, role in (
                ("新闻分析师", "news"), ("基本面分析师", "funda"),
                ("技术分析师", "tech"), ("风控分析师", "risk"),
                ("投资组合经理", "pm"),
            ):
                if role_marker in sys_text:
                    self.role_order.append(role)
                    break
            self.calls.append(kwargs)
            time.sleep(0.2)
            return _FakeResp(RolledFakeClient._RESPONSES[role_marker])

    class _SlowClient:
        def __init__(self):
            self.messages = _SlowMessages()

    _seed_ticker(session)
    slow = _SlowClient()
    t0 = time.perf_counter()
    run_decision(session, ticker="NVDA", client=slow, persist=False, parallel=True)
    elapsed = time.perf_counter() - t0
    # 4 analysts in parallel ≈ 0.2s, PM sequential ≈ 0.2s → ~0.4-0.5s total.
    # Sequential would be 5 × 0.2 = 1.0s. Anything under 0.75s proves parallelism.
    assert elapsed < 0.75, f"parallelism not effective: {elapsed:.3f}s"
    # PM must be last regardless of how the 4 analysts interleave.
    assert slow.messages.role_order[-1] == "pm"


def test_run_decision_sequential_mode_works(session):
    """parallel=False is the deterministic debug path; must still produce the
    same bundle shape."""
    _seed_ticker(session)
    fake = RolledFakeClient()
    bundle = run_decision(session, ticker="NVDA", client=fake, persist=False, parallel=False)
    assert bundle.decision == "buy"
    assert len(fake.messages.calls) == 5


def test_render_report_surfaces_guardrail():
    md = render_report(
        {"pm": {"decision": "hold", "guardrail_notes": ["原 buy 已降为 hold"]},
         "news": {}, "funda": {}, "tech": {"indicators": {}}, "risk": {}},
        ticker="X",
    )
    assert "guardrail" in md
    assert "降为 hold" in md
