"""Thin wrapper around the Anthropic SDK with prompt caching enabled.

We default to:
  - claude-haiku-4-5  for per-item triage / summarization (cheap + fast)
  - claude-sonnet-4-6 for daily digest / deep multi-doc synthesis

Prompt caching is applied to the system block so the editorial style + tracked
company list are reused across calls. See:
https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
"""
from __future__ import annotations

from functools import lru_cache

from anthropic import Anthropic

from intel.analysis.jsonparse import coerce_json
from intel.config.loader import load_companies
from intel.config.settings import settings


@lru_cache(maxsize=1)
def _client() -> Anthropic:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return Anthropic(api_key=settings.anthropic_api_key)


def _company_brief() -> str:
    rows = []
    for c in load_companies():
        tag = ",".join(c.get("tags") or [])
        flag = " (private)" if c.get("private") else ""
        rows.append(f"- {c['ticker']:<10} {c['name']}{flag}  [{tag}]")
    return "\n".join(rows)


SYSTEM_PROMPT = """你是一名专注全球 AI 产业的投研分析师。
工作目标:阅读用户给出的英文/中文新闻、公告或研报,产出对二级市场有价值、可操作的中文情报。

输出要求:
1. 用 5-8 句中文摘要核心事实(不要复述原文措辞);
2. 评估对相关上市公司的潜在影响:利好 / 利空 / 中性,影响等级:高 / 中 / 低;
3. 给出受影响标的列表(用 ticker,如 NVDA、9988.HK,只能从下面给出的跟踪清单中选);
4. 标注主题标签(如 算力、芯片、推理、训练框架、数据中心、监管、融资、出海 等);
5. 一句"为什么有/无影响"的简短理由。

下面是当前跟踪的 AI 产业上市/未上市公司清单(仅可在此清单中挑选 ticker):
"""


def _system_blocks() -> list[dict]:
    body = SYSTEM_PROMPT + "\n" + _company_brief()
    return [
        {
            "type": "text",
            "text": body,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def analyze_news(*, title: str, body: str, model: str | None = None) -> dict:
    """Return a dict with summary_zh / impact / sentiment / affected_tickers / themes / rationale."""
    client = _client()
    user_text = (
        f"## 标题\n{title}\n\n## 正文 / 摘要\n{(body or '')[:6000]}\n\n"
        "请输出严格 JSON,字段:summary_zh, impact(high/medium/low),"
        " direction(positive/negative/neutral), affected_tickers(数组),"
        " themes(数组), rationale。"
    )
    resp = client.messages.create(
        model=model or settings.model_fast,
        max_tokens=900,
        system=_system_blocks(),
        messages=[{"role": "user", "content": user_text}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return coerce_json(text)


def synthesize_digest(*, items: list[dict], model: str | None = None, period: str = "daily") -> str:
    """Combine multiple analyzed items into one Markdown brief."""
    client = _client()
    bullet_input = "\n\n".join(
        f"- [{i.get('impact','?').upper()}] {i.get('title','')}\n  影响标的:{','.join(i.get('affected_tickers') or [])}\n  摘要:{i.get('summary_zh','')}\n  来源:{i.get('url','')}"
        for i in items[:60]
    )
    instruction = (
        "你正在为一名 AI 产业基金经理写一份" + ("当日" if period == "daily" else "本周") + "情报简报。\n"
        "结构:\n"
        "1. 顶部:3-5 条「最值得关注」的要点(粗体标的 ticker);\n"
        "2. 「重点公司动态」按公司分组:NVDA / MSFT / GOOGL / META / AMZN / TSLA / AMD / 国内 等;\n"
        "3. 「赛道与主题」总结(算力 / 大模型 / 应用 / 监管 / 出海);\n"
        "4. 末尾:风险与待跟踪事项 3 条。\n"
        "用中文 Markdown,不要表情符号,正文简洁有信息密度。\n\n"
        f"原始材料:\n{bullet_input}"
    )
    resp = client.messages.create(
        model=model or settings.model_deep,
        max_tokens=2400,
        system=_system_blocks(),
        messages=[{"role": "user", "content": instruction}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


