# AI 产业投资情报系统 (`intel`)

[![ci](https://github.com/chenxiaomi2025-dev/claude-code-sandbox-/actions/workflows/ci.yml/badge.svg)](https://github.com/chenxiaomi2025-dev/claude-code-sandbox-/actions/workflows/ci.yml)

一个聚焦**全球 AI 产业**的命令行投研情报系统。两层能力:

1. **情报层**:自动采集英中文新闻 / 研报 / 论文 / SEC 披露 / 财报日 / 行情,
   用 Claude 完成摘要 + 影响评估 + 每日简报。
2. **决策层**:**5-agent 投研团队**(news / funda / tech / risk / pm),
   仿 TauricResearch [TradingAgents](https://github.com/TauricResearch/TradingAgents)
   架构,跑 `intel decide NVDA` 就能拿到 Buy/Hold/Avoid 的投资决策 + Markdown 报告。

## 设计目标

| 模块 | 内容 |
| --- | --- |
| 资产范围 | 全球 AI 产业链(芯片 / 云 / 模型实验室 / 应用 / 监管) |
| 数据源 | RSS(英文 + 中文)、arXiv、Hacker News、SEC EDGAR、yfinance(行情 + 财报日) |
| 形式 | CLI(`intel`) + 本地 SQLite |
| 智能层 | Anthropic Claude(Haiku 做分析师三审,Sonnet 做 PM 综合),启用 prompt caching |
| 工程 | pytest(≥91 用例)+ ruff + GitHub Actions CI(Python 3.10/3.11/3.12) |

## 5-Agent 决策流

```
                      intel decide NVDA
                              │
                       ┌──────┴──────┐
                       │ Coordinator │
                       └──────┬──────┘
                              ↓
   ┌──────────┬──────────┬──────────┬──────────┐
   ↓          ↓          ↓          ↓          ↓
 News      Funda      Tech       Risk        ...
 agent     agent      agent      agent
 (读       (读 SEC    (本地算    (复用
 news +    备案 +     MA/RSI/    detect_
 analyses) yfinance   动量)      alerts +
           财务比率)              回撤)
   │          │          │          │
   └────┬─────┴────┬─────┴────┬─────┘
        ↓          ↓          ↓
   4 份结构化 JSON 输入
                              ↓
                       ┌──────┴──────┐
                       │  PM agent   │ ← bull/bear 辩论 + 硬约束 guardrail
                       │  (Sonnet)   │   (risk=high + bear>bull → 强制 hold)
                       └──────┬──────┘
                              ↓
                  Decision row (DB) + Markdown report
```

每个 agent 输出 JSON + 中文正文;`tech`/`risk` 会把"确定可算"的字段
(RSI、MA、open_alerts 等)用 Python 算好再覆盖到 LLM 输出上,避免数据
被模型幻觉污染。PM 的输出会经过 `_enforce_constraints()` 安全网:
若 `risk.overall_risk='high'` 且 bear 多于 bull,自动把 buy 降为 hold。

## 目录结构

```
src/intel/
├── cli/main.py              # typer CLI:init/collect/analyze/digest/alerts/export/decide/...
├── collectors/              # rss / arxiv / hackernews / sec_edgar / quotes / earnings
│   └── runner.py            # 统一调度,幂等写库
├── analysis/
│   ├── llm.py               # Anthropic SDK 封装(prompt caching)
│   ├── jsonparse.py         # LLM JSON 输出容错解析(纯函数)
│   ├── pipeline.py          # 调度未分析新闻 + 生成 digest
│   ├── alerts.py            # 规则告警:财报 / 监管 / 高管 / 融资 / 高影响 / earnings_upcoming
│   ├── indicators.py        # 零依赖 SMA / RSI / 动量 / 回撤 / 金叉死叉
│   └── render.py            # Markdown → HTML 邮件渲染(零依赖)
├── agents/                  # 5-agent 投研团队
│   ├── base.py              # AgentResult + run_agent()(可注入 client,便于测试)
│   ├── news_agent.py        # 催化剂提取
│   ├── funda_agent.py       # SEC + yfinance 基本面快照
│   ├── tech_agent.py        # 技术指标 + 关键位
│   ├── risk_agent.py        # alerts + 回撤 + 临近财报
│   ├── pm_agent.py          # bull/bear 辩论 + decision + guardrail
│   └── coordinator.py       # 编排 5 agent + 持久化 Decision
├── storage/                 # SQLAlchemy ORM + 仓储函数(含 decisions / earnings_events 表)
└── config/
    ├── companies.yaml       # 跟踪标的清单(含中文 aliases)
    ├── sources.yaml         # 数据源清单(英 + 中文 RSS)
    └── settings.py          # 读 .env 的运行配置

tests/                       # pytest:91 用例,覆盖 agents/indicators/alerts/repo/...
.github/workflows/ci.yml     # ruff + pytest on Python 3.10/3.11/3.12
```

## 快速开始

```bash
# 1. 装依赖(推荐用 venv)
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. 配置 Claude API key
cp .env.example .env
$EDITOR .env  # 填 ANTHROPIC_API_KEY

# 3. 初始化数据库
intel init

# 4. 跑一次全量采集(RSS / arXiv / HN / EDGAR)
intel collect

# 5. 让 Claude 分析最近 30 条
intel analyze --limit 30

# 6. 生成今日 AI 产业简报
intel digest --hours 24
```

## 常用命令

```bash
# === 数据采集 ===
intel collect                      # 跑全部数据源
intel collect --kind rss           # 只跑 RSS
intel collect --kind sec_edgar     # 抓 EDGAR 备案
intel collect --kind yfinance      # 抓行情
intel collect --kind earnings      # 抓未来财报日

# === 浏览 ===
intel latest --hours 12            # 最近 12 小时新闻
intel search "blackwell"           # 关键字搜(中英文都支持)
intel company NVDA                 # 看单公司情报
intel companies                    # 看跟踪清单
intel calendar --days 14           # 未来 14 天财报日历

# === 情报层(单条 / 全局) ===
intel analyze --limit 50           # Claude 摘要+影响评估未处理新闻
intel digest --hours 24            # 当日简报(Sonnet)
intel alerts --hours 48 --severity high   # 规则告警
intel export --out today.html      # 渲染 HTML 邮件

# === 决策层(5-agent 投研团队) ===
intel agent news NVDA              # 单跑 NewsAgent(看催化剂)
intel agent funda NVDA             # 单跑 FundaAgent(基本面快照)
intel agent tech NVDA              # 单跑 TechAgent(技术面 + 关键位)
intel agent risk NVDA              # 单跑 RiskAgent(风险评级)
intel decide NVDA                  # 全流水线 → buy/hold/avoid + 报告
```

### `intel decide` 输出样例

```markdown
# NVDA 投研决策 · BUY
_置信度 72% · 时段 medium · 生成于 2026-06-02 14:51 UTC_

## 投资论断
算力周期延续,B300 推理芯片单卡 ASP 翻倍 ...

## Bull 论据
- B300 路线图 2026 Q3 大批量出货
- 推理 ASP 上行,毛利率扩张

## Bear 论据
- P/E 偏高,估值已 price in 大部分增长

## 关键风险
- 出口管制下一轮变更

## 重点跟踪事项
- FY26Q1 财报(T-20d)

## 分析师快照
- news: bullish (conf 0.8)
- funda: narrative=strong
- tech: view=bullish (RSI 68, MA cross golden)
- risk: overall_risk=medium, open_alerts=1, near_earnings=False
```

## 测试与 CI

```bash
pip install -e ".[dev]"
pytest                # 37 个单元测试
ruff check src tests  # 风格检查
```

CI 在 push / PR 时自动运行 ruff + pytest(Python 3.10/3.11/3.12)。

## 自定义跟踪范围

- **加公司**:编辑 `src/intel/config/companies.yaml`,加一项
  `{ticker, name, exchange, cik, tags}`。`cik` 是 SEC 的 10 位编号,只有想抓
  EDGAR 才需要(可在 https://www.sec.gov/cgi-bin/browse-edgar 查)。
- **加数据源**:编辑 `src/intel/config/sources.yaml`,在 `rss:` 下追加
  `{name, url, weight}` 即可。

## 数据模型

| 表 | 用途 |
| --- | --- |
| `companies` | 跟踪标的(含 ticker / cik / 私有标记 / tags) |
| `sources`   | 数据源元数据(kind / name / url / weight / last_fetched_at) |
| `news_items`| 新闻原始记录,含 `tickers`(自动关键词标注) |
| `analyses`  | Claude 分析结果(摘要、影响等级、情绪、主题、受影响标的) |
| `quotes`    | 日线 OHLCV(从 yfinance 抓) |
| `filings`   | SEC 备案(10-K/10-Q/8-K/...) |
| `digests`   | 历史简报正文 |

幂等写入:RSS / EDGAR / arXiv / HN 都用稳定的 `external_id` 主键,重复抓取不会写
重。

## Claude API 用法说明

- 模型默认:Haiku 4.5 做单条三审 / Sonnet 4.6 做日报合成。可通过
  `INTEL_MODEL_FAST` / `INTEL_MODEL_DEEP` 环境变量覆盖。
- 启用了 prompt caching:把"风格说明 + 跟踪公司清单"放在 system 块里加
  `cache_control`,跨条新闻命中缓存,显著降低成本。
- 单条分析强约束 JSON 输出(失败时降级保留原文)。

## Roadmap

- [x] 中文新闻源 RSS(36氪 / 量子位 / 机器之心 / 虎嗅 / InfoQ)
- [x] 中文公司别名匹配(英伟达 → NVDA、Kimi → MOONSHOT 等)
- [x] 规则事件告警(财报、监管、高管、融资、高影响)
- [x] Markdown → HTML 邮件渲染
- [x] GitHub Actions CI + 91 单元测试
- [x] 财报日历 + T-N 临近告警
- [x] **5-agent 投研团队 + `intel decide`**
- [x] 技术指标库(MA / RSI / 动量 / 回撤,零依赖)
- [x] PM agent 硬约束 guardrail(risk=high 自动降级 buy → hold)
- [ ] SMTP / Telegram 推送(目前只生成 HTML)
- [ ] 接入 A 股研报(慧博 / 东方财富 / 巨潮)
- [ ] Hacker News 评论摘要 / Reddit r/MachineLearning 舆情
- [ ] 回测引擎(基于 quotes + decisions 信号)
- [ ] Web 看板(Streamlit / FastAPI)

## 致谢

多 agent 架构灵感来自 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
(2024-2026 论文 [arXiv:2412.20138](https://arxiv.org/abs/2412.20138))。
我们用 5 个角色(news / funda / tech / risk / pm)做了精简化适配。

## 开发约定

- 新增 collector 都返回 `RawItem`,由 `runner.py` 统一持久化。
- 任何依赖外网的调用都封装在 `collectors/` 或 `analysis/` 内,核心模块不要
  直连 HTTP。
- DB 操作走 `session_scope()`,避免裸 session。
