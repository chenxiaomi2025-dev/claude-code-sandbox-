"""`intel` CLI entry point."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from intel.agents.funda_agent import run_funda_agent
from intel.agents.news_agent import run_news_agent
from intel.agents.tech_agent import run_tech_agent
from intel.analysis.alerts import detect_alerts
from intel.analysis.pipeline import analyze_pending, build_digest
from intel.analysis.render import render_email
from intel.collectors.runner import collect_all
from intel.storage.db import init_db, session_scope
from intel.storage.repo import (
    all_companies,
    get_company,
    news_for_ticker,
    recent_news,
    search_news,
    upcoming_earnings,
)

app = typer.Typer(help="AI 产业投资情报系统 (intel)")
console = Console()


@app.command()
def init():
    """初始化数据库与种子表。"""
    init_db()
    # importing companies into DB happens during first collect; do it now too
    from intel.config.loader import load_companies
    from intel.storage.repo import upsert_company

    with session_scope() as s:
        for c in load_companies():
            upsert_company(
                s,
                ticker=c["ticker"],
                name=c["name"],
                exchange=c.get("exchange"),
                cik=c.get("cik"),
                private=bool(c.get("private", False)),
                tags=c.get("tags"),
            )
    console.print("[green]数据库已初始化,公司清单已写入。[/green]")


@app.command()
def collect(
    kind: str | None = typer.Option(
        None,
        "--kind",
        "-k",
        help="只跑某一类采集器:rss / arxiv / hackernews / sec_edgar / yfinance",
    ),
):
    """采集所有(或指定类型)数据源。"""
    kinds = (kind,) if kind else None
    results = collect_all(kinds=kinds)
    table = Table(title="采集结果", show_lines=False)
    table.add_column("数据源")
    table.add_column("抓取", justify="right")
    table.add_column("新增", justify="right")
    table.add_column("失败", justify="right")
    for name, st in results.items():
        table.add_row(name, str(st.fetched), str(st.new), str(st.failed))
    console.print(table)


@app.command()
def analyze(
    limit: int = typer.Option(30, help="本次最多分析多少条未处理新闻"),
    model: str | None = typer.Option(None, help="覆盖默认 Claude 模型"),
):
    """对未分析的新闻调用 Claude 做摘要+影响评估。"""
    n = analyze_pending(limit=limit, model=model)
    console.print(f"[green]已分析 {n} 条新闻。[/green]")


@app.command()
def digest(
    hours: int = typer.Option(24, help="汇总最近多少小时的情报"),
    period: str = typer.Option("daily", help="daily 或 weekly"),
    model: str | None = typer.Option(None, help="覆盖默认 Claude 模型"),
):
    """生成一份 Markdown 投研简报。"""
    md = build_digest(hours=hours, period=period, model=model)
    console.print(Markdown(md))


@app.command()
def latest(
    hours: int = typer.Option(24, help="最近多少小时"),
    limit: int = typer.Option(40, help="最多展示多少条"),
):
    """看最近的原始新闻清单(不调用 Claude)。"""
    init_db()
    since = datetime.utcnow() - timedelta(hours=hours)
    with session_scope() as s:
        items = recent_news(s, since=since, limit=limit)
        table = Table(title=f"最近 {hours}h 新闻 ({len(items)})", show_lines=False)
        table.add_column("时间", style="cyan")
        table.add_column("标的")
        table.add_column("标题")
        for it in items:
            t = it.published_at.strftime("%m-%d %H:%M") if it.published_at else "-"
            table.add_row(t, ",".join(it.tickers or []) or "-", it.title[:90])
        console.print(table)


@app.command()
def search(query: str, limit: int = 30):
    """全文搜索数据库中的新闻。"""
    init_db()
    with session_scope() as s:
        rows = search_news(s, query, limit=limit)
        if not rows:
            console.print("[yellow]没有匹配结果。[/yellow]")
            return
        table = Table(title=f"匹配「{query}」({len(rows)})")
        table.add_column("时间", style="cyan")
        table.add_column("标的")
        table.add_column("标题")
        for r in rows:
            t = r.published_at.strftime("%m-%d %H:%M") if r.published_at else "-"
            table.add_row(t, ",".join(r.tickers or []) or "-", r.title[:90])
        console.print(table)


@app.command()
def company(ticker: str, days: int = 14, limit: int = 30):
    """看某只标的的最近情报与档案。"""
    init_db()
    ticker = ticker.upper()
    with session_scope() as s:
        c = get_company(s, ticker)
        if not c:
            console.print(f"[red]{ticker} 不在跟踪清单。可在 src/intel/config/companies.yaml 中添加。[/red]")
            raise typer.Exit(1)
        console.print(f"[bold]{c.ticker}[/bold]  {c.name}  ({c.exchange or '-'})  tags={c.tags}")
        rows = news_for_ticker(s, ticker, days=days, limit=limit)
        table = Table(title=f"{ticker} 最近 {days} 天情报 ({len(rows)})")
        table.add_column("时间", style="cyan")
        table.add_column("影响")
        table.add_column("标题")
        for r in rows:
            t = r.published_at.strftime("%m-%d %H:%M") if r.published_at else "-"
            impact = "-"
            if r.analyses:
                latest = max(r.analyses, key=lambda a: a.created_at)
                impact = (latest.impact or "-").upper()
            table.add_row(t, impact, r.title[:80])
        console.print(table)


@app.command()
def export(
    out: Path = typer.Option(Path("data/exports/digest.html"), help="输出 HTML 路径"),
    hours: int = typer.Option(24, help="简报覆盖窗口"),
    period: str = typer.Option("daily", help="daily / weekly"),
    skip_llm: bool = typer.Option(False, "--skip-llm", help="不调用 Claude,只渲染最近一份已生成的 digest"),
):
    """把最新 digest + alerts 渲染成可邮件发送的 HTML。"""
    init_db()
    md = ""
    if skip_llm:
        from sqlalchemy import select

        from intel.storage.models import Digest

        with session_scope() as s:
            d = s.execute(select(Digest).order_by(Digest.created_at.desc()).limit(1)).scalar_one_or_none()
            md = d.body_md if d else "_数据库内尚无 digest,先跑一次 `intel digest`。_"
    else:
        md = build_digest(hours=hours, period=period)
    with session_scope() as s:
        all_alerts = detect_alerts(s, hours=hours)
    html_body = render_email(digest_md=md, alerts=all_alerts, hours=hours)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_body, encoding="utf-8")
    console.print(f"[green]HTML 已写入 {out} ({len(html_body):,} bytes, {len(all_alerts)} 告警)[/green]")


@app.command()
def alerts(
    hours: int = typer.Option(48, help="扫描最近多少小时"),
    severity: str = typer.Option("low", help="最低严重性:critical/high/medium/low"),
):
    """扫描已采集情报,输出关键事件清单(基于规则,不调用 LLM)。"""
    init_db()
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    threshold = rank.get(severity.lower(), 3)
    with session_scope() as s:
        items = detect_alerts(s, hours=hours)
        items = [a for a in items if rank.get(a.severity, 9) <= threshold]
        if not items:
            console.print("[green]没有触发告警的事件。[/green]")
            return
        table = Table(title=f"事件告警 ({len(items)})")
        table.add_column("严重性", style="bold")
        table.add_column("类型")
        table.add_column("时间", style="cyan")
        table.add_column("标的")
        table.add_column("标题")
        sev_color = {"high": "red", "medium": "yellow", "low": "white", "critical": "red bold"}
        for a in items:
            t = a.when.strftime("%m-%d %H:%M")
            table.add_row(
                f"[{sev_color.get(a.severity,'white')}]{a.severity.upper()}[/]",
                a.kind,
                t,
                ",".join(a.tickers) or "-",
                a.title[:80],
            )
        console.print(table)


@app.command()
def agent(
    role: str = typer.Argument(..., help="agent 角色:news (后续会有 funda/tech/risk/pm)"),
    ticker: str = typer.Argument(..., help="标的 ticker,例如 NVDA"),
    days: int = typer.Option(14, help="新闻回看窗口(天)"),
    model: str | None = typer.Option(None, help="覆盖默认 Claude 模型"),
):
    """跑单个 agent。当前已实现:news。后续迭代加入 funda/tech/risk/pm。"""
    init_db()
    ticker = ticker.upper()
    runners = {
        "news": lambda s: run_news_agent(s, ticker=ticker, days=days, model=model),
        "funda": lambda s: run_funda_agent(s, ticker=ticker, days=days, model=model),
        "tech": lambda s: run_tech_agent(s, ticker=ticker, days=max(60, days), model=model),
    }
    if role not in runners:
        console.print(f"[red]未知角色:{role}。当前可用:{', '.join(runners)}[/red]")
        raise typer.Exit(1)
    with session_scope() as s:
        result = runners[role](s)
    console.print(
        f"[bold]{role} agent[/bold]  ticker={ticker}  model={result.model}  "
        f"tokens=in/{result.tokens_in} out/{result.tokens_out} cache_read/{result.cache_read}"
    )
    console.print(Markdown(result.output_md))


@app.command()
def calendar(days: int = typer.Option(14, help="向后看多少天的财报日")):
    """显示未来 N 天的财报日历。先跑 `intel collect --kind earnings` 采集。"""
    init_db()
    with session_scope() as s:
        rows = upcoming_earnings(s, within_days=days)
        if not rows:
            console.print(
                "[yellow]还没有财报数据。先跑 `intel collect --kind earnings`(需要 yfinance + 网络)。[/yellow]"
            )
            return
        table = Table(title=f"未来 {days} 天财报 ({len(rows)})")
        table.add_column("日期", style="cyan")
        table.add_column("Ticker", style="bold")
        table.add_column("公司")
        table.add_column("距今")
        now = datetime.utcnow()
        for ev, comp in rows:
            d = (ev.expected_date - now).days
            table.add_row(
                ev.expected_date.strftime("%Y-%m-%d"),
                comp.ticker,
                comp.name,
                f"T-{max(0, d)}d",
            )
        console.print(table)


@app.command()
def companies():
    """列出当前跟踪的所有公司。"""
    init_db()
    with session_scope() as s:
        rows = all_companies(s)
        table = Table(title=f"跟踪清单 ({len(rows)})")
        table.add_column("Ticker")
        table.add_column("Name")
        table.add_column("Exchange")
        table.add_column("Tags")
        for c in rows:
            table.add_row(c.ticker, c.name, c.exchange or "-", ",".join(c.tags or []))
        console.print(table)


if __name__ == "__main__":
    app()
