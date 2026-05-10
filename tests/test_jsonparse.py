from intel.analysis.jsonparse import coerce_json


def test_direct_json():
    out = coerce_json('{"impact":"high","themes":["chip"]}')
    assert out["impact"] == "high"
    assert out["themes"] == ["chip"]


def test_fenced_json():
    blob = """这是模型的回答
```json
{"impact": "medium", "affected_tickers": ["NVDA","AMD"]}
```
后面是噪音"""
    out = coerce_json(blob)
    assert out["impact"] == "medium"
    assert out["affected_tickers"] == ["NVDA", "AMD"]


def test_brace_extraction():
    blob = "Hello {\"impact\": \"low\", \"direction\": \"neutral\"} trailing"
    out = coerce_json(blob)
    assert out["direction"] == "neutral"


def test_fallback_keeps_text():
    out = coerce_json("纯自然语言,没有 JSON")
    assert out["impact"] == "low"
    assert "summary_zh" in out
    assert out["summary_zh"].startswith("纯自然语言")


def test_empty_input():
    out = coerce_json("")
    assert out["affected_tickers"] == []


def test_array_top_level_falls_back_to_text():
    # we expect a dict; an array should not silently mutate keys
    out = coerce_json("[1,2,3]")
    assert isinstance(out, dict)
    assert "summary_zh" in out
