"""Tests for the multi-agent framework using a fake Anthropic client."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intel.agents.base import run_agent
from intel.agents.news_agent import build_user_message, gather_context, run_news_agent
from intel.storage.repo import add_analysis, upsert_news

# --------- fake client plumbing ---------

@dataclass
class _FakeBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 20


@dataclass
class _FakeResponse:
    content: list
    usage: _FakeUsage


class FakeMessages:
    def __init__(self, fake_text: str):
        self.fake_text = fake_text
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(content=[_FakeBlock(text=self.fake_text)], usage=_FakeUsage())


class FakeClient:
    def __init__(self, fake_text: str):
        self.messages = FakeMessages(fake_text)


# --------- tests ---------

def test_run_agent_parses_json_and_returns_usage():
    fake = FakeClient(
        '```json\n{"impact":"high","tickers":["NVDA"]}\n```\n这是中文正文。'
    )
    out = run_agent(
        role="news", system="you are an analyst", user="hi", client=fake, model="claude-haiku-4-5"
    )
    assert out.role == "news"
    assert out.output_json["impact"] == "high"
    assert "NVDA" in out.output_json["tickers"]
    assert "这是中文正文" in out.output_md
    assert out.tokens_in == 100
    assert out.tokens_out == 50
    assert out.cache_read == 20
    assert out.model == "claude-haiku-4-5"


def test_run_agent_passes_cache_control_in_system():
    fake = FakeClient('{"ok":true}')
    run_agent(role="news", system="ROLE PROMPT", user="hi", client=fake)
    call = fake.messages.calls[0]
    sys_blocks = call["system"]
    assert isinstance(sys_blocks, list) and len(sys_blocks) == 1
    assert sys_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert sys_blocks[0]["text"] == "ROLE PROMPT"


def test_run_agent_falls_back_on_bad_json():
    fake = FakeClient("纯自然语言,没有 JSON 块")
    out = run_agent(role="news", system="x", user="y", client=fake)
    # coerce_json returns its fallback dict
    assert "summary_zh" in out.output_json or out.output_json.get("raw")


def test_news_user_message_empty_case():
    msg = build_user_message(ticker="NVDA", news_rows=[], window_days=14)
    assert "NVDA" in msg
    assert "数据不足" in msg or "没有匹配" in msg


def test_news_user_message_has_rows():
    rows = [
        {
            "date": "2026-05-01",
            "title": "Blackwell B300 ramp ahead of schedule",
            "url": "https://example.com/1",
            "summary": "summary text",
            "summary_zh": "中文摘要",
            "impact": "high",
            "direction": "positive",
        }
    ]
    msg = build_user_message(ticker="NVDA", news_rows=rows, window_days=14)
    assert "Blackwell B300" in msg
    assert "high" in msg


def test_news_gather_context(session):
    n, _ = upsert_news(
        session,
        source_id=None,
        external_id="ext::a1",
        url="https://x/1",
        title="NVDA Blackwell ramp",
        summary="brief",
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=["NVDA"],
    )
    add_analysis(
        session,
        news_id=n.id,
        model="haiku",
        summary_zh="英伟达加速 Blackwell 出货",
        impact="high",
        sentiment=0.6,
    )
    rows = gather_context(session, ticker="NVDA", days=14)
    assert len(rows) == 1
    r = rows[0]
    assert r["impact"] == "high"
    assert r["direction"] == "positive"
    assert "英伟达" in r["summary_zh"]


def test_run_news_agent_end_to_end(session):
    upsert_news(
        session,
        source_id=None,
        external_id="ext::a1",
        url="https://x/1",
        title="NVDA news 1",
        summary="s1",
        content=None,
        author=None,
        published_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        lang="en",
        tags=None,
        tickers=["NVDA"],
    )
    fake = FakeClient(
        '```json\n{"ticker":"NVDA","window_days":14,"net_view":"bullish","confidence":0.7,"catalysts":[]}\n```\n'
        "三句中文分析。"
    )
    result = run_news_agent(session, ticker="NVDA", days=14, client=fake)
    assert result.output_json["ticker"] == "NVDA"
    assert result.output_json["net_view"] == "bullish"
    # the agent's system prompt is what was sent
    call = fake.messages.calls[0]
    assert "新闻分析师" in call["system"][0]["text"]
