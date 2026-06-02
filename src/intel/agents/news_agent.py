"""NewsAgent: surface the top recent catalysts for a tracked ticker.

Reads from `news_items` + `analyses` filtered by ticker, condenses the past
N days into a ranked list of catalysts (event, impact, why-it-matters).

Output JSON schema:
{
  "ticker": str,
  "window_days": int,
  "catalysts": [
    {"date": "YYYY-MM-DD", "title": str, "impact": "high|medium|low",
     "direction": "positive|negative|neutral", "summary": str, "url": str}
  ],
  "net_view": "bullish|bearish|neutral",
  "confidence": float (0-1)
}
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from intel.agents.base import JSON_FOOTER, AgentResult, run_agent
from intel.storage.repo import news_for_ticker

SYSTEM = (
    "你是 AI 投研团队中的【新闻分析师】。"
    "工作目标:把给定标的最近 N 天的新闻流压缩成 3-6 条对股价/估值有影响的催化剂,"
    "并给出整体多空倾向。"
    "原则:1) 只看事实,不臆测;2) 同一事件多源报道合并为一条;"
    "3) 区分'已发生'与'传闻'/'预期';4) 标注 impact 与 direction。"
    + JSON_FOOTER
)


def build_user_message(*, ticker: str, news_rows: list[dict], window_days: int) -> str:
    if not news_rows:
        return (
            f"标的:{ticker}\n窗口:最近 {window_days} 天\n\n"
            "本窗口内没有匹配该标的的新闻条目。请输出空 catalysts 列表,"
            "net_view='neutral',confidence=0.2,并在正文说明数据不足。"
        )
    bullet = []
    for r in news_rows[:40]:
        date = r["date"]
        impact = r.get("impact") or "-"
        bullet.append(
            f"- [{date}] [{impact}] {r['title']}\n  摘要:{r.get('summary_zh') or r.get('summary') or '-'}\n  来源:{r['url']}"
        )
    return (
        f"标的:{ticker}\n窗口:最近 {window_days} 天\n\n"
        f"原始新闻条目({len(news_rows)} 条):\n" + "\n\n".join(bullet)
    )


def gather_context(session: Session, *, ticker: str, days: int = 14) -> list[dict]:
    rows = news_for_ticker(session, ticker, days=days, limit=60)
    out: list[dict] = []
    now = datetime.utcnow()
    for n in rows:
        latest = max(n.analyses, key=lambda a: a.created_at) if n.analyses else None
        date_obj = n.published_at or n.fetched_at or now
        out.append(
            {
                "date": date_obj.strftime("%Y-%m-%d"),
                "title": n.title,
                "url": n.url,
                "summary": n.summary,
                "summary_zh": latest.summary_zh if latest else None,
                "impact": latest.impact if latest else None,
                "direction": (
                    "positive"
                    if latest and (latest.sentiment or 0) > 0.1
                    else "negative"
                    if latest and (latest.sentiment or 0) < -0.1
                    else "neutral"
                ),
            }
        )
    return out


def run_news_agent(
    session: Session,
    *,
    ticker: str,
    days: int = 14,
    client=None,
    model: str | None = None,
) -> AgentResult:
    rows = gather_context(session, ticker=ticker, days=days)
    user = build_user_message(ticker=ticker, news_rows=rows, window_days=days)
    return run_agent(
        role="news",
        system=SYSTEM,
        user=user,
        model=model,
        client=client,
        max_tokens=1400,
    )


__all__ = ["run_news_agent", "gather_context", "build_user_message", "SYSTEM"]
