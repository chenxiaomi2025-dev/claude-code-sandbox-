from intel.config.loader import company_keywords, load_companies, load_sources


def test_companies_loaded():
    cs = load_companies()
    tickers = {c["ticker"] for c in cs}
    assert "NVDA" in tickers
    assert "OPENAI" in tickers
    assert len(cs) >= 20


def test_sources_have_expected_kinds():
    s = load_sources()
    assert "rss" in s and len(s["rss"]) >= 5
    assert "arxiv" in s
    assert "hackernews" in s


def test_company_keywords_excludes_private_tickers():
    kw = company_keywords()
    # private labs should not include their pseudo-ticker as a keyword
    assert "OPENAI" not in kw["OPENAI"]
    assert "OpenAI" in kw["OPENAI"]
    # listed companies should include both name and ticker
    assert "NVDA" in kw["NVDA"]
    assert "NVIDIA" in kw["NVDA"]
