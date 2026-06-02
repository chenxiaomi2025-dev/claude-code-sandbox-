"""RiskAgent: risk & exposure assessment.

Combines the rule-based alerts engine output, drawdown from price data, and
upcoming earnings into a structured risk dossier. Claude is asked to grade
overall risk and surface the top 3 risks the PM should know about.

Output JSON:
{
  "ticker": str,
  "overall_risk": "high|medium|low",
  "near_earnings": bool,
  "open_alerts": int,
  "top_risks": [{"category": str, "detail": str}],
  "rationale": str
}
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from intel.agents.base import JSON_FOOTER, AgentResult, run_agent
from intel.analysis.alerts import detect_alerts
from intel.analysis.indicators import drawdown
from intel.storage.models import Company, Quote
from intel.storage.repo import upcoming_earnings

SYSTEM = (
    "你是 AI 投研团队中的【风控分析师】。"
    "工作目标:基于规则告警、回撤、临近财报、监管暴露,"
    "给出一个 overall_risk 评级以及最值得 PM 关注的 3 条风险。"
    "原则:1) 临近财报 (T-3d) 或回撤 > 20% 直接 'high';"
    "2) 监管类告警权重最高;"
    "3) 没有数据时不要编风险,如实写 'low' 并在 rationale 说明。"
    + JSON_FOOTER
)


def gather_context(session: Session, *, ticker: str, hours: int = 168) -> dict:
    company = session.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
    if company is None:
        return {
            "ticker": ticker, "alerts": [], "drawdown_pct": None, "earnings": [], "tags": []
        }
    all_alerts = detect_alerts(session, hours=hours)
    ticker_alerts = [
        {
            "severity": a.severity,
            "kind": a.kind,
            "title": a.title,
            "when": a.when.strftime("%Y-%m-%d"),
        }
        for a in all_alerts
        if ticker in (a.tickers or [])
    ]
    since = datetime.utcnow() - timedelta(days=120)
    closes = [
        q.close
        for q in session.execute(
            select(Quote)
            .where(Quote.company_id == company.id, Quote.date >= since)
            .order_by(Quote.date.asc())
        ).scalars()
        if q.close is not None
    ]
    upcoming = upcoming_earnings(session, within_days=14)
    near = [
        (ev.expected_date - datetime.utcnow()).days
        for ev, comp in upcoming
        if comp.ticker == ticker
    ]
    return {
        "ticker": ticker,
        "tags": company.tags or [],
        "alerts": ticker_alerts,
        "drawdown_pct": drawdown(closes),
        "earnings": near,
    }


def build_user_message(ctx: dict) -> str:
    lines = [f"标的:{ctx['ticker']}"]
    if ctx.get("tags"):
        lines.append("标签:" + ",".join(ctx["tags"]))

    alerts = ctx.get("alerts") or []
    lines.append(f"\n相关告警({len(alerts)} 条):")
    if not alerts:
        lines.append("  - 无")
    else:
        for a in alerts[:20]:
            lines.append(f"  - [{a['severity'].upper()}] {a['when']} {a['kind']}: {a['title']}")

    earnings = ctx.get("earnings") or []
    if earnings:
        days = min(earnings)
        lines.append(f"\n临近财报:最近一次 T-{days}d")
    else:
        lines.append("\n临近财报:未来 14 天内无")

    dd = ctx.get("drawdown_pct")
    if dd is not None:
        lines.append(f"\n回撤:{dd:.2f}% (相对样本期高点)")
    else:
        lines.append("\n回撤:数据不足")

    lines.append(
        "\n请输出 JSON(字段:ticker, overall_risk, near_earnings, open_alerts,"
        " top_risks[{category,detail}], rationale),再用中文 4-6 句解释风险全景。"
    )
    return "\n".join(lines)


def run_risk_agent(
    session: Session,
    *,
    ticker: str,
    hours: int = 168,
    client=None,
    model: str | None = None,
) -> AgentResult:
    ctx = gather_context(session, ticker=ticker, hours=hours)
    user = build_user_message(ctx)
    result = run_agent(
        role="risk",
        system=SYSTEM,
        user=user,
        model=model,
        client=client,
        max_tokens=1200,
    )
    # Inject the deterministic counts so PM agent can trust them
    if isinstance(result.output_json, dict):
        result.output_json.setdefault("ticker", ticker)
        result.output_json["open_alerts"] = len(ctx.get("alerts") or [])
        result.output_json["near_earnings"] = bool(ctx.get("earnings"))
    return result


__all__ = ["run_risk_agent", "gather_context", "build_user_message", "SYSTEM"]
