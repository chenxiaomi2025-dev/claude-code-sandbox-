"""LLM JSON output coercion (tolerant parser).

Lives in its own module so tests don't need the anthropic SDK installed.
"""
from __future__ import annotations

import json
import re
from typing import Any


def coerce_json(text: str) -> dict[str, Any]:
    """Best-effort parse of a model's JSON output.

    Strategy:
    1. Direct json.loads of stripped text.
    2. Pull out a fenced ```json ... ``` block.
    3. Take the first balanced { ... } substring.
    4. Fallback: stash the raw text under summary_zh.
    """
    text = (text or "").strip()
    if not text:
        return _fallback("")

    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        try:
            out = json.loads(fence.group(1))
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass

    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            out = json.loads(brace.group(0))
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass

    return _fallback(text)


def _fallback(text: str) -> dict[str, Any]:
    return {
        "summary_zh": text[:600],
        "impact": "low",
        "direction": "neutral",
        "affected_tickers": [],
        "themes": [],
        "rationale": "JSON 解析失败,已存原文摘要",
    }
