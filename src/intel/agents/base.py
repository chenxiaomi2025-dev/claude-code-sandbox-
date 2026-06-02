"""Multi-agent investment research framework.

Each agent is a single-shot LLM call with a tight role contract:
  - INPUT  : structured dict (the data the agent needs from the DB)
  - OUTPUT : AgentResult { output_md: str, output_json: dict }

This file provides the shared base + a thin Anthropic wrapper that:
  - applies prompt caching to the role system block
  - injects the agent-specific user message
  - parses JSON output via intel.analysis.jsonparse.coerce_json
  - lets tests inject a fake client (any object with .messages.create)

Roles (planned, added one per iteration):
  news      — what just happened to this ticker in the last N days
  funda     — fundamentals snapshot from filings + quotes
  tech      — price action / momentum / MA cross from quotes
  risk      — alerts + concentration / regulatory exposure
  pm        — portfolio-manager synthesis → buy/hold/avoid + confidence
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from intel.analysis.jsonparse import coerce_json
from intel.config.settings import settings


@dataclass
class AgentResult:
    role: str
    output_md: str
    output_json: dict[str, Any]
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0


class _ClientLike(Protocol):
    """Minimum interface tests need to satisfy."""

    @property
    def messages(self) -> Any: ...


def _default_client():
    """Lazy-import the real Anthropic SDK so tests can run without it."""
    from anthropic import Anthropic

    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return Anthropic(api_key=settings.anthropic_api_key)


def run_agent(
    *,
    role: str,
    system: str,
    user: str,
    model: str | None = None,
    client: _ClientLike | None = None,
    max_tokens: int = 1200,
) -> AgentResult:
    """Run a single agent call. Returns AgentResult with parsed JSON + the
    raw markdown body produced by the model.

    Convention: agents are asked to emit one fenced ```json``` block
    containing a structured object, followed by a human-readable Markdown
    summary. We parse the JSON via coerce_json (tolerant), and return the
    full text as output_md.
    """
    used_client = client or _default_client()
    used_model = model or settings.model_fast
    resp = used_client.messages.create(
        model=used_model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    parsed = coerce_json(text)
    usage = getattr(resp, "usage", None)
    return AgentResult(
        role=role,
        output_md=text,
        output_json=parsed if isinstance(parsed, dict) else {"raw": text[:600]},
        model=used_model,
        tokens_in=getattr(usage, "input_tokens", 0) or 0,
        tokens_out=getattr(usage, "output_tokens", 0) or 0,
        cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )


# A tiny output-format snippet every agent can append to its prompt to keep
# the schema stable across roles.
JSON_FOOTER = (
    "\n\n输出格式:先用 ```json``` 包裹一个对象(字段见 schema 提示),"
    "再换行用中文给出 5-8 句的分析正文。不要在 JSON 之前写任何文字。"
)


@dataclass
class AgentSpec:
    """Declarative agent definition. Used by the coordinator to enumerate
    available roles."""

    role: str
    description: str
    system_prompt: str
    builder: Callable[..., str] = field(repr=False)  # builds the user message
    json_schema_hint: str = ""
