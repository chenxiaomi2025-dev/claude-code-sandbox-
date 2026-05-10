"""Render the latest digest + alerts as standalone HTML for email/web.

Pure-Python markdown → HTML so we don't pull in any extra dependency.
Supports just enough syntax to render Claude's digest output cleanly:

  - # / ## / ### headings
  - bullet lists (-, *)
  - **bold**, *italic*, `code`
  - autolink http(s)://...
  - paragraphs separated by blank lines
"""
from __future__ import annotations

import html
import re
from collections.abc import Iterable
from datetime import datetime

from intel.analysis.alerts import Alert

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_CODE = re.compile(r"`([^`]+)`")
_LINK_AUTO = re.compile(r"(https?://[^\s)\]]+)")
_LINK_MD = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def md_to_html(md: str) -> str:
    """Minimal markdown → HTML."""
    if not md:
        return ""
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    in_list = False
    para: list[str] = []

    def flush_para():
        nonlocal para
        if para:
            text = " ".join(para).strip()
            if text:
                out.append(f"<p>{_inline(text)}</p>")
            para = []

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        if not line.strip():
            flush_para()
            close_list()
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            flush_para()
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        m = re.match(r"^[-*]\s+(.+)$", line)
        if m:
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue

        close_list()
        para.append(line)
        i += 1

    flush_para()
    close_list()
    return "\n".join(out)


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = _LINK_MD.sub(lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', text)
    text = _LINK_AUTO.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    text = _CODE.sub(r"<code>\1</code>", text)
    return text


_HTML_TEMPLATE = """<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif; max-width: 760px; margin: 24px auto; padding: 0 16px; color: #1a1a1a; line-height: 1.55; }}
    h1, h2, h3 {{ line-height: 1.25; }}
    h1 {{ border-bottom: 2px solid #222; padding-bottom: 6px; }}
    h2 {{ margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .meta {{ color: #666; font-size: 13px; margin-bottom: 16px; }}
    .alerts {{ margin: 24px 0; }}
    .alert {{ border-left: 4px solid #ccc; padding: 8px 12px; margin: 8px 0; background: #fafafa; }}
    .alert.high {{ border-left-color: #dc2626; }}
    .alert.medium {{ border-left-color: #f59e0b; }}
    .alert.low {{ border-left-color: #6b7280; }}
    .alert .kind {{ display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 3px; background: #eee; color: #333; margin-right: 6px; }}
    .alert .tickers {{ color: #444; font-weight: 600; font-size: 13px; }}
    code {{ background: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-size: 90%; }}
    ul {{ padding-left: 22px; }}
    li {{ margin: 3px 0; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <div class="meta">{generated_at} · 范围 {hours}h{alerts_count_meta}</div>
  {alerts_block}
  <article>
{body_html}
  </article>
</body>
</html>
"""


def render_email(*, digest_md: str, alerts: Iterable[Alert], hours: int, title: str = "AI 产业情报简报") -> str:
    """Render a self-contained HTML email containing alerts + digest body."""
    alerts = list(alerts)
    blocks = []
    if alerts:
        blocks.append('<section class="alerts"><h2>关键事件</h2>')
        for a in alerts[:30]:
            tickers = ", ".join(a.tickers) if a.tickers else "-"
            url_attr = html.escape(a.url, quote=True) if a.url else ""
            anchor = f'<a href="{url_attr}">链接</a>' if url_attr else ""
            blocks.append(
                f'<div class="alert {html.escape(a.severity)}">'
                f'<span class="kind">{html.escape(a.kind)}</span>'
                f'<span class="tickers">{html.escape(tickers)}</span>'
                f' · {html.escape(a.title)} {anchor}'
                f'<div style="color:#555;font-size:12px;">{html.escape(a.rationale)}</div>'
                f'</div>'
            )
        blocks.append("</section>")
    return _HTML_TEMPLATE.format(
        title=html.escape(title),
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        hours=hours,
        alerts_count_meta=f" · {len(alerts)} 条告警" if alerts else "",
        alerts_block="\n".join(blocks),
        body_html=md_to_html(digest_md),
    )
