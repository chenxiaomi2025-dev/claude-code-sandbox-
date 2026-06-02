"""Coordinator: orchestrate news → funda → tech → risk → pm into one decision.

This is the top of the agent graph. It runs each analyst sequentially
(parallel is possible but rarely useful given per-account rate limits and
because PM depends on all 4), then hands their structured JSON outputs to
the PM agent for synthesis. The whole bundle plus a rendered Markdown
report is persisted to the `decisions` table.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from intel.agents import funda_agent, news_agent, risk_agent, tech_agent
from intel.agents.base import AgentResult, run_agent
from intel.agents.pm_agent import run_pm_agent
from intel.storage.repo import save_decision


@dataclass
class DecisionBundle:
    ticker: str
    news: AgentResult
    funda: AgentResult
    tech: AgentResult
    risk: AgentResult
    pm: AgentResult
    report_md: str
    db_id: int | None = None

    @property
    def decision(self) -> str:
        return (self.pm.output_json.get("decision") or "hold").lower()

    @property
    def confidence(self) -> float | None:
        v = self.pm.output_json.get("confidence")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def horizon(self) -> str | None:
        return self.pm.output_json.get("horizon")


def render_report(bundle_payload: dict, *, ticker: str) -> str:
    """Compose a Markdown report from the agent payload dict."""
    pm = bundle_payload.get("pm") or {}
    news = bundle_payload.get("news") or {}
    funda = bundle_payload.get("funda") or {}
    tech = bundle_payload.get("tech") or {}
    risk = bundle_payload.get("risk") or {}

    decision = (pm.get("decision") or "?").upper()
    conf = pm.get("confidence")
    conf_str = f"{conf:.0%}" if isinstance(conf, (int, float)) else "n/a"
    horizon = pm.get("horizon") or "n/a"

    parts = [
        f"# {ticker} 投研决策 · {decision}",
        f"_置信度 {conf_str} · 时段 {horizon} · 生成于 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "## 投资论断",
        pm.get("thesis") or "_PM 未给出 thesis_",
        "",
        "## Bull 论据",
    ]
    parts += [f"- {p}" for p in (pm.get("bull_points") or [])] or ["- _无_"]
    parts += ["", "## Bear 论据"]
    parts += [f"- {p}" for p in (pm.get("bear_points") or [])] or ["- _无_"]
    parts += ["", "## 关键风险"]
    parts += [f"- {p}" for p in (pm.get("key_risks") or [])] or ["- _无_"]
    parts += ["", "## 重点跟踪事项"]
    parts += [f"- {p}" for p in (pm.get("monitor") or [])] or ["- _无_"]

    if pm.get("guardrail_notes"):
        parts += ["", "## ⚠️ 系统 guardrail 修订"]
        parts += [f"- {n}" for n in pm["guardrail_notes"]]

    parts += [
        "",
        "## 分析师快照",
        f"- **news**: {news.get('net_view') or '?'} (conf {news.get('confidence')})",
        f"- **funda**: narrative={funda.get('narrative_score') or '?'}",
        f"- **tech**: view={tech.get('tech_view') or '?'} "
        f"(RSI {tech.get('indicators', {}).get('rsi14')}, MA cross {tech.get('indicators', {}).get('ma_cross')})",
        f"- **risk**: overall_risk={risk.get('overall_risk') or '?'}, "
        f"open_alerts={risk.get('open_alerts')}, near_earnings={risk.get('near_earnings')}",
    ]
    return "\n".join(parts)


def _execute_analyst(
    *,
    role: str,
    ticker: str,
    system: str,
    user: str,
    max_tokens: int,
    overlay: dict | None,
    overlay_mode: str,
    client,
    model: str | None,
) -> AgentResult:
    """Run one analyst LLM call and apply role-specific deterministic overlays.

    overlay_mode:
      - 'replace_indicators': set output_json['indicators'] = overlay
      - 'merge_counts'      : output_json.update(overlay)  (used by RiskAgent)
      - 'none'              : leave output_json alone
    """
    result = run_agent(
        role=role, system=system, user=user, model=model, client=client, max_tokens=max_tokens,
    )
    if isinstance(result.output_json, dict):
        result.output_json.setdefault("ticker", ticker)
        if overlay_mode == "replace_indicators" and overlay is not None:
            result.output_json["indicators"] = overlay
        elif overlay_mode == "merge_counts" and overlay is not None:
            result.output_json.update(overlay)
    return result


def _prepare_analyst_tasks(
    session: Session,
    *,
    ticker: str,
    news_days: int,
    funda_days: int,
    tech_days: int,
    risk_hours: int,
) -> list[dict]:
    """Read all DB context in the main thread and return a list of self-
    contained task dicts that can be dispatched to a thread pool.

    Every value returned here is a primitive / plain dict — no ORM objects
    that would lazy-load across threads.
    """
    # ---- news ----
    news_rows = news_agent.gather_context(session, ticker=ticker, days=news_days)
    news_msg = news_agent.build_user_message(ticker=ticker, news_rows=news_rows, window_days=news_days)

    # ---- funda ----
    funda_ctx = funda_agent.gather_context(session, ticker=ticker, days=funda_days)
    funda_msg = funda_agent.build_user_message(funda_ctx, days=funda_days)

    # ---- tech ---- (deterministic indicators get overlaid post-call)
    tech_ctx = tech_agent.gather_context(session, ticker=ticker, days=tech_days)
    tech_msg = tech_agent.build_user_message(tech_ctx)

    # ---- risk ---- (deterministic alert count + near_earnings get merged)
    risk_ctx = risk_agent.gather_context(session, ticker=ticker, hours=risk_hours)
    risk_msg = risk_agent.build_user_message(risk_ctx)

    return [
        {
            "role": "news",
            "system": news_agent.SYSTEM,
            "user": news_msg,
            "max_tokens": 1400,
            "overlay": None,
            "overlay_mode": "none",
        },
        {
            "role": "funda",
            "system": funda_agent.SYSTEM,
            "user": funda_msg,
            "max_tokens": 1400,
            "overlay": None,
            "overlay_mode": "none",
        },
        {
            "role": "tech",
            "system": tech_agent.SYSTEM,
            "user": tech_msg,
            "max_tokens": 1200,
            "overlay": tech_ctx["summary"],
            "overlay_mode": "replace_indicators",
        },
        {
            "role": "risk",
            "system": risk_agent.SYSTEM,
            "user": risk_msg,
            "max_tokens": 1200,
            "overlay": {
                "open_alerts": len(risk_ctx.get("alerts") or []),
                "near_earnings": bool(risk_ctx.get("earnings")),
            },
            "overlay_mode": "merge_counts",
        },
    ]


def run_decision(
    session: Session,
    *,
    ticker: str,
    news_days: int = 14,
    funda_days: int = 30,
    tech_days: int = 120,
    risk_hours: int = 168,
    client=None,
    model_fast: str | None = None,
    model_deep: str | None = None,
    persist: bool = True,
    parallel: bool = True,
) -> DecisionBundle:
    """Run the full agent pipeline for a single ticker.

    Analysts (news/funda/tech/risk) run in a thread pool because their LLM
    calls are I/O bound (HTTP to Anthropic). The PM agent runs sequentially
    afterwards since it depends on all 4 analyst outputs. Set parallel=False
    for deterministic ordering when debugging.
    """
    tasks = _prepare_analyst_tasks(
        session,
        ticker=ticker,
        news_days=news_days,
        funda_days=funda_days,
        tech_days=tech_days,
        risk_hours=risk_hours,
    )

    def _run(task):
        return _execute_analyst(
            role=task["role"], ticker=ticker, system=task["system"], user=task["user"],
            max_tokens=task["max_tokens"], overlay=task["overlay"], overlay_mode=task["overlay_mode"],
            client=client, model=model_fast,
        )

    results: dict[str, AgentResult] = {}
    if parallel:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for task, fut in zip(tasks, [pool.submit(_run, t) for t in tasks], strict=True):
                results[task["role"]] = fut.result()
    else:
        for task in tasks:
            results[task["role"]] = _run(task)

    news = results["news"]
    funda = results["funda"]
    tech = results["tech"]
    risk = results["risk"]

    pm = run_pm_agent(
        ticker=ticker,
        news_json=news.output_json,
        funda_json=funda.output_json,
        tech_json=tech.output_json,
        risk_json=risk.output_json,
        client=client,
        model=model_deep,
    )
    payload = {
        "news": news.output_json,
        "funda": funda.output_json,
        "tech": tech.output_json,
        "risk": risk.output_json,
        "pm": pm.output_json,
        "tokens": {
            "news": news.tokens_in + news.tokens_out,
            "funda": funda.tokens_in + funda.tokens_out,
            "tech": tech.tokens_in + tech.tokens_out,
            "risk": risk.tokens_in + risk.tokens_out,
            "pm": pm.tokens_in + pm.tokens_out,
        },
    }
    report_md = render_report(payload, ticker=ticker)
    bundle = DecisionBundle(
        ticker=ticker,
        news=news, funda=funda, tech=tech, risk=risk, pm=pm,
        report_md=report_md,
    )
    if persist:
        row = save_decision(
            session,
            ticker=ticker,
            decision=bundle.decision,
            confidence=bundle.confidence,
            horizon=bundle.horizon,
            pm_model=pm.model,
            payload=payload,
            report_md=report_md,
        )
        bundle.db_id = row.id
    return bundle


__all__ = ["run_decision", "render_report", "DecisionBundle"]
