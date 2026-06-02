from intel.agents.pm_agent import _enforce_constraints, build_user_message, run_pm_agent
from tests.test_agents import FakeClient


def test_build_user_message_digests_all_roles():
    msg = build_user_message(
        ticker="NVDA",
        news_json={"net_view": "bullish", "confidence": 0.8, "catalysts": [{"a": 1}]},
        funda_json={"narrative_score": "strong"},
        tech_json={"tech_view": "bullish", "indicators": {"rsi14": 68}},
        risk_json={"overall_risk": "medium", "open_alerts": 2},
    )
    assert "NVDA" in msg
    assert "net_view=bullish" in msg
    assert "narrative_score=strong" in msg
    assert "overall_risk=medium" in msg


def test_build_user_message_handles_missing_inputs():
    msg = build_user_message(
        ticker="OPENAI", news_json=None, funda_json=None, tech_json=None, risk_json=None
    )
    assert "OPENAI" in msg
    assert "无数据" in msg


def test_guardrail_downgrades_buy_when_risk_high_and_weak_bull():
    out = _enforce_constraints(
        {"decision": "buy", "confidence": 0.9, "bull_points": ["x"], "bear_points": ["a", "b", "c"]},
        risk_json={"overall_risk": "high"},
    )
    assert out["decision"] == "hold"
    assert out["confidence"] <= 0.5
    assert any("强制降为 hold" in n for n in out["guardrail_notes"])


def test_guardrail_keeps_buy_when_risk_high_but_bull_dominates():
    out = _enforce_constraints(
        {"decision": "buy", "confidence": 0.7, "bull_points": ["a", "b", "c", "d"], "bear_points": ["e"]},
        risk_json={"overall_risk": "high"},
    )
    assert out["decision"] == "buy"
    assert out.get("guardrail_notes") is None


def test_guardrail_noop_when_risk_not_high():
    out = _enforce_constraints(
        {"decision": "buy", "confidence": 0.9, "bull_points": [], "bear_points": []},
        risk_json={"overall_risk": "medium"},
    )
    assert out["decision"] == "buy"
    assert out["confidence"] == 0.9


def test_run_pm_agent_end_to_end():
    fake = FakeClient(
        '```json\n'
        '{"ticker":"NVDA","decision":"hold","confidence":0.55,"horizon":"medium",'
        '"thesis":"算力强但临近财报","bull_points":["B300 路线图清晰"],'
        '"bear_points":["P/E 高","出口管制"],"key_risks":["监管"],"monitor":["FY26Q1"]}\n```\n'
        "中文 PM 备忘。"
    )
    out = run_pm_agent(
        ticker="NVDA",
        news_json={"net_view": "bullish"},
        funda_json={"narrative_score": "strong"},
        tech_json={"tech_view": "bullish"},
        risk_json={"overall_risk": "medium"},
        client=fake,
        model="claude-sonnet-4-6",
    )
    assert out.role == "pm"
    assert out.output_json["decision"] == "hold"
    assert out.output_json["confidence"] == 0.55
    # The PM system prompt mentions 投资组合经理
    call = fake.messages.calls[0]
    assert "投资组合经理" in call["system"][0]["text"]


def test_run_pm_agent_applies_guardrail():
    fake = FakeClient(
        '```json\n'
        '{"decision":"buy","confidence":0.95,"bull_points":["x"],"bear_points":["a","b","c"]}\n```'
    )
    out = run_pm_agent(
        ticker="X",
        news_json={"net_view": "bearish"},
        funda_json={"narrative_score": "weak"},
        tech_json={"tech_view": "bearish"},
        risk_json={"overall_risk": "high"},
        client=fake,
    )
    assert out.output_json["decision"] == "hold"
    assert out.output_json["confidence"] <= 0.5
