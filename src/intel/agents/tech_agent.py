"""TechAgent: technical-analysis narrative from indicators computed locally.

We do the math ourselves (intel.analysis.indicators), then hand a small
summary dict to Claude so it can produce a readable view + a structured
tech_view (bullish/bearish/neutral) and an entry/exit hint.

Output JSON:
{
  "ticker": str,
  "indicators": {ma5, ma20, ma60, rsi14, mom_5d, mom_20d, drawdown_pct, ma_cross},
  "tech_view": "bullish|bearish|neutral",
  "key_levels": {"support": float|null, "resistance": float|null},
  "rationale": str
}
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from intel.agents.base import JSON_FOOTER, AgentResult, run_agent
from intel.analysis.indicators import summarize
from intel.storage.models import Company, Quote

SYSTEM = (
    "你是 AI 投研团队中的【技术分析师】。"
    "工作目标:基于给定的 MA / 动量 / RSI / 回撤 / 均线交叉指标,"
    "给出技术面观点(bullish/bearish/neutral)与近端支撑/阻力位的估计。"
    "原则:1) 指标无效或数据不足时,输出 'neutral' + 数据不足说明;"
    "2) RSI > 70 注意超买,< 30 注意超卖;"
    "3) 5/20 均线金叉 + 动量 > 0 才支持 bullish;"
    "4) 关键位用整数或最近高/低点四舍五入。"
    + JSON_FOOTER
)


def gather_context(session: Session, *, ticker: str, days: int = 90) -> dict:
    company = session.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
    if company is None:
        return {"ticker": ticker, "closes": [], "summary": summarize([])}

    since = datetime.utcnow() - timedelta(days=days)
    quotes = list(
        session.execute(
            select(Quote)
            .where(Quote.company_id == company.id, Quote.date >= since)
            .order_by(Quote.date.asc())
        ).scalars()
    )
    closes = [q.close for q in quotes if q.close is not None]
    return {
        "ticker": ticker,
        "name": company.name,
        "closes": closes,
        "first_date": quotes[0].date.strftime("%Y-%m-%d") if quotes else None,
        "last_date": quotes[-1].date.strftime("%Y-%m-%d") if quotes else None,
        "summary": summarize(closes),
    }


def _fmt(v):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def build_user_message(ctx: dict) -> str:
    s = ctx["summary"]
    lines = [
        f"标的:{ctx['ticker']} ({ctx.get('name') or '-'})",
        f"样本:{s['n']} 个交易日 ({ctx.get('first_date') or '-'} → {ctx.get('last_date') or '-'})",
        "",
        "指标快照:",
        f"  - 最新收盘:{_fmt(s['last'])}",
        f"  - MA5 / MA20 / MA60:{_fmt(s['ma5'])} / {_fmt(s['ma20'])} / {_fmt(s['ma60'])}",
        f"  - 动量 5d / 20d / 60d:{_fmt(s['mom_5d'])}% / {_fmt(s['mom_20d'])}% / {_fmt(s['mom_60d'])}%",
        f"  - RSI(14):{_fmt(s['rsi14'])}",
        f"  - 区间高/低回撤:{_fmt(s['drawdown_pct'])}%",
        f"  - MA5 vs MA20:{s['ma_cross']}",
        "",
        "请给出 JSON(字段:ticker, indicators, tech_view, key_levels{support,resistance}, rationale),"
        "再用中文 4-6 句解释技术面。",
    ]
    return "\n".join(lines)


def run_tech_agent(
    session: Session,
    *,
    ticker: str,
    days: int = 90,
    client=None,
    model: str | None = None,
) -> AgentResult:
    ctx = gather_context(session, ticker=ticker, days=days)
    user = build_user_message(ctx)
    result = run_agent(
        role="tech",
        system=SYSTEM,
        user=user,
        model=model,
        client=client,
        max_tokens=1200,
    )
    # Always overlay the deterministic indicators into the JSON output so
    # downstream consumers can trust the numbers even if the model hallucinates.
    if isinstance(result.output_json, dict):
        result.output_json.setdefault("ticker", ticker)
        result.output_json["indicators"] = ctx["summary"]
    return result


__all__ = ["run_tech_agent", "gather_context", "build_user_message", "SYSTEM"]
