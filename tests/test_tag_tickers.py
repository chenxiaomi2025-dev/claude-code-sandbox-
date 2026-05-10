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


def test_chinese_aliases_match():
    out = tag_tickers("英伟达发布新款 Blackwell 芯片,阿里通义千问跟进")
    assert "NVDA" in out
    assert "BABA" in out


def test_chinese_two_char_alias():
    out = tag_tickers("腾讯混元发布新版本")
    assert "0700.HK" in out


def test_kimi_and_deepseek_chinese():
    out = tag_tickers("月之暗面 Kimi 与深度求索 DeepSeek 同日发布")
    assert "MOONSHOT" in out
    assert "DEEPSEEK" in out
