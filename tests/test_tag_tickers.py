from intel.collectors.base import tag_tickers


def test_tag_by_company_name():
    text = "NVIDIA unveils Blackwell GPU; OpenAI says it will use them."
    out = tag_tickers(text)
    assert "NVDA" in out
    assert "OPENAI" in out


def test_tag_by_ticker_symbol():
    out = tag_tickers("Earnings beat from NVDA and AMD on Tuesday.")
    assert "NVDA" in out
    assert "AMD" in out


def test_no_tickers_for_unrelated_text():
    out = tag_tickers("Today the weather is sunny.")
    assert out == []


def test_short_tokens_dont_false_positive():
    # short keys like "AI" must not be matched (length filter)
    out = tag_tickers("AI is everywhere")
    assert out == []


def test_returns_sorted_unique():
    out = tag_tickers("Microsoft and Microsoft again, plus Anthropic")
    assert out == sorted(set(out))
    assert "MSFT" in out
    assert "ANTHROPIC" in out
