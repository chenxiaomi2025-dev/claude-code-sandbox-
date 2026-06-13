# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`ai-intel` (CLI name: `intel`) is a command-line AI-industry investment research
system. It has two layers built on the same SQLite store:

1. **Intelligence layer** — collect English/Chinese news, arXiv, Hacker News, SEC
   EDGAR filings, quotes, and earnings dates; use Claude to summarize + score
   impact; emit a daily digest and rule-based alerts.
2. **Decision layer** — a 5-agent research team (news / funda / tech / risk / pm)
   that turns `intel decide NVDA` into a Buy/Hold/Avoid call plus a Markdown report.

Note: code is written in English; user-facing strings, prompts, and analyst
output are Chinese (中文). Keep that bilingual split when adding features.

## Commands

```bash
pip install -e ".[dev]"          # install with dev extras (pytest, ruff)

pytest                           # run all tests (~93, no API key needed)
pytest tests/test_pm_agent.py    # single file
pytest tests/test_agents.py::test_run_agent_parses_json_and_returns_usage  # single test
ruff check src tests             # lint (line-length 110; ignores E501, B008)

intel init                       # create SQLite schema at data/intel.db
intel collect [--kind rss|arxiv|hackernews|sec_edgar|yfinance|earnings]
intel analyze --limit 30         # Claude triage of unanalyzed news (needs ANTHROPIC_API_KEY)
intel digest --hours 24          # synthesize daily brief
intel decide NVDA                # full 5-agent pipeline → decision + report
intel agent news|funda|tech|risk NVDA   # run a single analyst
```

Tests run without an API key — every agent/LLM path accepts an injected fake
client (see `tests/conftest.py` and the `FakeClient` pattern in `tests/test_agents.py`).
CI runs ruff + pytest on Python 3.10/3.11/3.12.

## Configuration

- Runtime config comes from env vars, loaded in `config/settings.py` via a tiny
  hand-rolled `.env` parser (`os.environ.setdefault`, so real env vars win). The
  `settings` singleton is imported everywhere — do not re-read env directly.
- Key vars: `ANTHROPIC_API_KEY`, `INTEL_MODEL_FAST` (default `claude-haiku-4-5`),
  `INTEL_MODEL_DEEP` (default `claude-sonnet-4-6`), `INTEL_DB_PATH`.
- Tracked tickers live in `config/companies.yaml` (with Chinese `aliases`); data
  sources in `config/sources.yaml`. Add companies/sources by editing YAML, not code.

## Architecture

### Data flow (intelligence layer)
`collectors/*` each yield `RawItem` dataclasses. `collectors/runner.py` is the
**only** place that persists them — it walks `sources.yaml`, calls each collector,
tags tickers (`collectors/base.tag_tickers`, keyword/alias match with a CJK-aware
min-length filter), and upserts. All writes are **idempotent** via a stable
`external_id` primary-ish key, so re-collecting never duplicates rows.

### Storage
SQLAlchemy 2.0 ORM in `storage/models.py`; repository functions in `storage/repo.py`
(all `upsert_*` / query helpers). Always go through `storage/db.session_scope()`
(a commit/rollback context manager) — never construct bare sessions in app code.
Tables: `companies`, `sources`, `news_items`, `analyses`, `quotes`, `filings`,
`digests`, `decisions`, `earnings_events`.

### LLM access — two distinct entry points
- `analysis/llm.py` — intelligence-layer calls (`analyze_news`, `synthesize_digest`).
  Caches a module-level `Anthropic` client; puts editorial style + the tracked-company
  list in a `cache_control: ephemeral` system block so it's reused across calls.
- `agents/base.py:run_agent()` — decision-layer calls. Same prompt-caching idea but
  **accepts an injectable `client`** (`_ClientLike` protocol) for testing, and
  returns an `AgentResult` (parsed JSON + raw markdown + token usage).
- All model output is parsed with `analysis/jsonparse.coerce_json` (tolerant — strips
  fences, recovers from partial JSON; pure function, heavily tested).

### Agent framework (`agents/`)
Each analyst module follows the same shape: `SYSTEM` prompt + `gather_context(session,...)`
(reads DB → plain dicts) + `build_user_message(...)` + `run_<role>_agent(...)`.
Agents emit a fenced ```json``` block followed by Chinese prose (enforced by
`base.JSON_FOOTER`).

`agents/coordinator.py:run_decision()` is the orchestration top:
1. `_prepare_analyst_tasks()` reads **all** DB context in the main thread and
   returns self-contained primitive/dict tasks — deliberately so no ORM object is
   lazy-loaded across threads.
2. The 4 analysts run in a `ThreadPoolExecutor` (LLM calls are I/O bound);
   `parallel=False` forces sequential order for debugging.
3. PM (`agents/pm_agent.py`, defaults to the **deep** model) runs last since it
   depends on all 4 outputs, then the bundle + Markdown report is saved to `decisions`.

### Two correctness safeguards — preserve these when touching agents
- **Deterministic overlays**: `tech` and `risk` LLM output has machine-computed
  fields overwritten after the call (`_execute_analyst` overlay modes
  `replace_indicators` / `merge_counts`), so RSI/MA-cross/alert-counts come from
  Python (`analysis/indicators.py`, `analysis/alerts.py`), never from model guesses.
- **PM guardrail**: `pm_agent._enforce_constraints()` is a last-mile safety net —
  if `risk.overall_risk == "high"` and bear points ≥ bull points, a `buy` is forced
  to `hold` (capped confidence, annotated in `guardrail_notes`). Don't let the model
  be the only thing enforcing this rule.

## Conventions

- New collectors must return `RawItem` and be wired into `runner.py`; don't persist
  from within a collector.
- Network access lives only in `collectors/` and `analysis/`. Core/agent logic
  should receive data, not fetch it.
- `analysis/indicators.py` and `analysis/render.py` are intentionally zero-dependency
  (no numpy/pandas) — keep them that way.
- The CLI (`cli/main.py`, Typer) is a thin layer: it opens a `session_scope()` and
  delegates to `collectors`/`analysis`/`agents`. Keep business logic out of it.
