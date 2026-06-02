"""PMAgent: portfolio-manager synthesis with internal bull/bear debate.

Takes the structured outputs of the news / funda / tech / risk agents and
produces a final investment decision in a single Claude call. The model is
instructed to argue both sides before committing, which empirically improves
calibration vs. a flat "pick one" prompt (see TradingAgents 2024-2026 work).

Output JSON:
{
  "ticker": str,
  "decision": "buy|hold|avoid",
  "confidence": float (0-1),
  "horizon": "short|medium|long",
  "thesis": str,
  "bull_points": [str],
  "bear_points": [str],
  "key_risks": [str],
  "monitor": [str]      # what would change our mind
}
"""
from __future__ import annotations

from intel.agents.base import JSON_FOOTER, AgentResult, run_agent
from intel.config.settings import settings

SYSTEM = (
    "你是 AI 投研团队的【投资组合经理】。"
    "你会收到 4 位下属分析师的结构化输出:news / funda / tech / risk。"
    "工作流程(必须在脑内完成):"
    "1) 先生成 3-4 条 bull_points,引用上面的具体证据(不要空话);"
    "2) 再生成 3-4 条 bear_points,同样要有证据;"
    "3) 称重两边的相对强度,并参考 risk.overall_risk;"
    "4) 给出 decision(buy / hold / avoid)与 confidence(0-1)。"
    "硬约束:"
    "- 若 risk.overall_risk='high' 且 bull 不强,decision 不得 'buy';"
    "- news.net_view='bearish' 与 tech.tech_view='bullish' 冲突时,confidence 不得 > 0.6;"
    "- 数据不足时优先 'hold' 并在 thesis 里写清楚缺哪类数据。"
    + JSON_FOOTER
)


def _digest_agent_output(role: str, payload: dict | None) -> str:
    if not payload:
        return f"- {role}: 无数据"
    blob = []
    for k, v in payload.items():
        if v is None or v == [] or v == {}:
            continue
        if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
            v = f"{len(v)} items"
        blob.append(f"{k}={v}")
    return f"- {role}: " + "; ".join(blob[:14])


def build_user_message(
    *,
    ticker: str,
    news_json: dict | None,
    funda_json: dict | None,
    tech_json: dict | None,
    risk_json: dict | None,
) -> str:
    return (
        f"标的:{ticker}\n\n"
        "下属分析师输出(已结构化):\n"
        + _digest_agent_output("news", news_json) + "\n"
        + _digest_agent_output("funda", funda_json) + "\n"
        + _digest_agent_output("tech", tech_json) + "\n"
        + _digest_agent_output("risk", risk_json) + "\n\n"
        "请按 system 中的硬约束输出 JSON("
        "字段:ticker, decision, confidence, horizon, thesis,"
        " bull_points[], bear_points[], key_risks[], monitor[]"
        "),再用中文写 6-10 句投资笔记。"
    )


def run_pm_agent(
    *,
    ticker: str,
    news_json: dict | None = None,
    funda_json: dict | None = None,
    tech_json: dict | None = None,
    risk_json: dict | None = None,
    client=None,
    model: str | None = None,
) -> AgentResult:
    user = build_user_message(
        ticker=ticker,
        news_json=news_json,
        funda_json=funda_json,
        tech_json=tech_json,
        risk_json=risk_json,
    )
    # PM uses the deep model by default — synthesis matters more than speed
    used_model = model or settings.model_deep
    result = run_agent(
        role="pm",
        system=SYSTEM,
        user=user,
        model=used_model,
        client=client,
        max_tokens=2000,
    )
    if isinstance(result.output_json, dict):
        result.output_json.setdefault("ticker", ticker)
        # Enforce the hard constraints in code as a safety net.
        result.output_json = _enforce_constraints(result.output_json, risk_json=risk_json)
    return result


def _enforce_constraints(decision_json: dict, *, risk_json: dict | None) -> dict:
    """Last-mile guardrails. We never silently let the model violate the
    'no buy when risk=high' rule — we downgrade to 'hold' and annotate."""
    risk_level = (risk_json or {}).get("overall_risk", "").lower()
    if risk_level == "high" and decision_json.get("decision") == "buy":
        original = decision_json.get("decision")
        bull_strength = len(decision_json.get("bull_points") or [])
        bear_strength = len(decision_json.get("bear_points") or [])
        if bull_strength <= bear_strength:
            decision_json["decision"] = "hold"
            decision_json["confidence"] = min(decision_json.get("confidence", 0.5), 0.5)
            decision_json.setdefault("guardrail_notes", []).append(
                f"原 decision={original},因 risk=high 且 bull 论据不强,强制降为 hold"
            )
    return decision_json


__all__ = ["run_pm_agent", "build_user_message", "SYSTEM"]
