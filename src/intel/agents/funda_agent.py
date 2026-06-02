"""FundaAgent: fundamentals snapshot for a tracked ticker.

Reads recent SEC filings + price action summary from the local DB, plus an
optional yfinance financial-ratio snapshot when available. Hands the
compressed view to Claude for a fundamentals narrative.

Output JSON schema:
{
  "ticker": str,
  "valuation_signals": [str],         # e.g. ["P/E 32 vs sector 28", "MV $3T"]
  "recent_filings": [{"form": str, "filed_at": str, "url": str}],
  "key_metrics": {"market_cap": ..., "pe": ..., "ps": ..., ...},
  "narrative_score": "strong|neutral|weak",
  "rationale": str
}
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from intel.agents.base import JSON_FOOTER, AgentResult, run_agent
from intel.storage.models import Company, Filing, Quote

log = logging.getLogger("intel.agents.funda")

SYSTEM = (
    "你是 AI 投研团队中的【基本面分析师】。"
    "工作目标:基于 SEC 备案节奏、最近 30 天价格区间、以及可选的 yfinance 财务指标,"
    "给出一份简洁的基本面快照。"
    "原则:1) 没有数据的字段写 null,不要编造;"
    "2) 估值判断要相对(给出参考行业/历史区间);"
    "3) 区分'强 narrative'(收入加速、毛利率扩张)与'弱 narrative'(去库存、降价)。"
    + JSON_FOOTER
)


def _yfinance_snapshot(ticker: str) -> dict:
    """Best-effort financial ratios via yfinance. Returns {} on any failure."""
    try:
        import yfinance as yf
    except ImportError:
        return {}
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:
        log.warning("yfinance.info(%s) failed: %s", ticker, e)
        return {}
    keep = (
        "marketCap",
        "trailingPE",
        "forwardPE",
        "priceToSalesTrailing12Months",
        "profitMargins",
        "revenueGrowth",
        "earningsGrowth",
        "grossMargins",
        "operatingMargins",
        "totalRevenue",
        "freeCashflow",
        "currency",
        "sector",
        "industry",
    )
    return {k: info.get(k) for k in keep if info.get(k) is not None}


def gather_context(session: Session, *, ticker: str, days: int = 30) -> dict:
    company = session.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
    if company is None:
        return {"ticker": ticker, "filings": [], "price": None, "ratios": {}}

    since = datetime.utcnow() - timedelta(days=365)
    filings = list(
        session.execute(
            select(Filing)
            .where(Filing.company_id == company.id, Filing.filed_at >= since)
            .order_by(Filing.filed_at.desc())
            .limit(8)
        ).scalars()
    )
    filings_payload = [
        {"form": f.form, "filed_at": f.filed_at.strftime("%Y-%m-%d"), "url": f.url}
        for f in filings
    ]

    price_window_start = datetime.utcnow() - timedelta(days=days)
    quotes = list(
        session.execute(
            select(Quote)
            .where(Quote.company_id == company.id, Quote.date >= price_window_start)
            .order_by(Quote.date.asc())
        ).scalars()
    )
    price_payload: dict | None = None
    if quotes:
        closes = [q.close for q in quotes if q.close is not None]
        if closes:
            price_payload = {
                "first_close": closes[0],
                "last_close": closes[-1],
                "high": max(closes),
                "low": min(closes),
                "n_days": len(closes),
                "return_pct": (closes[-1] / closes[0] - 1) * 100 if closes[0] else None,
            }

    return {
        "ticker": ticker,
        "name": company.name,
        "exchange": company.exchange,
        "is_private": company.private,
        "tags": company.tags or [],
        "filings": filings_payload,
        "price": price_payload,
        "ratios": _yfinance_snapshot(ticker) if not company.private else {},
    }


def build_user_message(ctx: dict, *, days: int) -> str:
    lines = [f"标的:{ctx['ticker']} ({ctx.get('name')})  交易所:{ctx.get('exchange') or '-'}"]
    if ctx.get("is_private"):
        lines.append("注:未上市公司,仅有新闻/估值信号,无 SEC 备案与行情。")
    if ctx.get("tags"):
        lines.append("标签:" + ",".join(ctx["tags"]))

    filings = ctx.get("filings") or []
    if filings:
        lines.append(f"\n最近 SEC 备案({len(filings)} 条):")
        for f in filings:
            lines.append(f"  - [{f['filed_at']}] {f['form']}  {f['url']}")
    else:
        lines.append("\n最近 SEC 备案:无")

    price = ctx.get("price")
    if price:
        lines.append(
            f"\n最近 {price['n_days']} 个交易日价格:"
            f"开 {price['first_close']:.2f} → 收 {price['last_close']:.2f} "
            f"(区间 {price['low']:.2f} - {price['high']:.2f}, "
            f"涨幅 {price['return_pct']:+.2f}%)"
        )
    else:
        lines.append(f"\n最近 {days} 天行情:无数据")

    ratios = ctx.get("ratios") or {}
    if ratios:
        lines.append("\nyfinance 财务指标:")
        for k, v in ratios.items():
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("\nyfinance 财务指标:无")

    lines.append(
        "\n请输出 JSON(字段:ticker, valuation_signals[], recent_filings[],"
        " key_metrics{}, narrative_score, rationale),然后用中文写 5-7 句基本面快照。"
    )
    return "\n".join(lines)


def run_funda_agent(
    session: Session,
    *,
    ticker: str,
    days: int = 30,
    client=None,
    model: str | None = None,
) -> AgentResult:
    ctx = gather_context(session, ticker=ticker, days=days)
    user = build_user_message(ctx, days=days)
    return run_agent(
        role="funda",
        system=SYSTEM,
        user=user,
        model=model,
        client=client,
        max_tokens=1400,
    )


__all__ = ["run_funda_agent", "gather_context", "build_user_message", "SYSTEM"]
