from datetime import datetime

from intel.analysis.alerts import Alert
from intel.analysis.render import md_to_html, render_email


def test_headings_and_lists():
    md = "# 简报\n\n## 重点\n\n- 第一条\n- 第二条\n"
    html = md_to_html(md)
    assert "<h1>简报</h1>" in html
    assert "<h2>重点</h2>" in html
    assert "<ul>" in html and "</ul>" in html
    assert html.count("<li>") == 2


def test_bold_italic_code():
    html = md_to_html("**强** 与 *弱* 与 `code`")
    assert "<strong>强</strong>" in html
    assert "<em>弱</em>" in html
    assert "<code>code</code>" in html


def test_autolink_and_md_link():
    html = md_to_html("see https://anthropic.com and [Claude](https://claude.ai)")
    assert '<a href="https://anthropic.com">https://anthropic.com</a>' in html
    assert '<a href="https://claude.ai">Claude</a>' in html


def test_paragraph_separation():
    html = md_to_html("段落一\n\n段落二")
    assert html.count("<p>") == 2


def test_html_escapes_user_text():
    html = md_to_html("<script>alert(1)</script>")
    assert "<script>" not in html  # raw escaped
    assert "&lt;script&gt;" in html


def test_render_email_contains_digest_and_alerts():
    alerts = [
        Alert(
            severity="high",
            kind="earnings",
            title="NVDA 提交 10-Q",
            url="https://sec/x",
            tickers=["NVDA"],
            when=datetime(2026, 5, 9, 12, 0),
            rationale="SEC 备案 10-Q",
        )
    ]
    html = render_email(digest_md="# 简报\n\n- 要点 1", alerts=alerts, hours=24)
    assert "<!doctype html>" in html
    assert "AI 产业情报简报" in html
    assert "关键事件" in html
    assert "NVDA" in html
    assert "earnings" in html
    assert "<h1>简报</h1>" in html


def test_render_email_no_alerts():
    html = render_email(digest_md="正文", alerts=[], hours=12)
    assert "关键事件" not in html
    assert "12h" in html


def test_alert_severity_class_in_html():
    a = Alert(severity="high", kind="regulation", title="x", url="", tickers=[], when=datetime.utcnow(), rationale="")
    html = render_email(digest_md="", alerts=[a], hours=1)
    assert 'class="alert high"' in html
