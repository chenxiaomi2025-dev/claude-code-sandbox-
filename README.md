# AI 产业投资情报系统 (`intel`)

[![ci](https://github.com/chenxiaomi2025-dev/claude-code-sandbox-/actions/workflows/ci.yml/badge.svg)](https://github.com/chenxiaomi2025-dev/claude-code-sandbox-/actions/workflows/ci.yml)

一个聚焦**全球 AI 产业**的命令行投研情报系统:从公开数据源自动采集
新闻 / 研报 / 论文 / 监管披露 / 行情,再用 Claude 完成中文摘要、影响评估
和每日简报,数据全部落本地 SQLite。

## 设计目标

| 模块 | 内容 |
| --- | --- |
| 资产范围 | 全球 AI 产业链(芯片 / 云 / 模型实验室 / 应用 / 监管) |
| 数据源 | RSS(英文 + 中文)、arXiv、Hacker News、SEC EDGAR、yfinance |
| 形式 | CLI(`intel`) + 本地 SQLite |
| 智能层 | Anthropic Claude(Haiku 做单条三审,Sonnet 做综合简报),启用 prompt caching |
| 工程 | pytest(≥37 用例)+ ruff + GitHub Actions CI(Python 3.10/3.11/3.12) |

## 目录结构

```
src/intel/
├── cli/main.py              # typer CLI:init/collect/analyze/digest/alerts/export/...
├── collectors/              # rss / arxiv / hackernews / sec_edgar / quotes
│   └── runner.py            # 统一调度,幂等写库
├── analysis/
│   ├── llm.py               # Anthropic SDK 封装(prompt caching)
│   ├── jsonparse.py         # LLM JSON 输出容错解析(纯函数)
│   ├── pipeline.py          # 调度未分析新闻 + 生成 digest
│   ├── alerts.py            # 规则告警:财报 / 监管 / 高管 / 融资 / 高影响
│   └── render.py            # Markdown → HTML 邮件渲染(零依赖)
├── storage/                 # SQLAlchemy ORM + 仓储函数
└── config/
    ├── companies.yaml       # 跟踪标的清单(含中文 aliases)
    ├── sources.yaml         # 数据源清单(英 + 中文 RSS)
    └── settings.py          # 读 .env 的运行配置

tests/                       # pytest:jsonparse / tag_tickers / config / repo / alerts / render
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
# 采集
intel collect                      # 跑全部数据源
intel collect --kind rss           # 只跑 RSS
intel collect --kind sec_edgar     # 抓 EDGAR 备案
intel collect --kind yfinance      # 抓行情

# 浏览
intel latest --hours 12            # 最近 12 小时新闻
intel search "blackwell"           # 关键字搜(中英文都支持)
intel company NVDA                 # 看单公司情报
intel companies                    # 看跟踪清单

# AI 分析
intel analyze --limit 50           # Claude 摘要+影响评估未处理新闻
intel digest --hours 24            # 当日简报(Sonnet)
intel digest --hours 168 --period weekly  # 周报

# 告警与导出(不调用 LLM)
intel alerts --hours 48 --severity high   # 规则告警(财报/监管/高管/融资)
intel export --out data/exports/today.html        # 渲染 HTML 邮件
intel export --skip-llm                            # 不调 LLM,复用最近一份 digest
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
- [x] GitHub Actions CI + 37 单元测试
- [ ] SMTP / Telegram 推送(目前只生成 HTML)
- [ ] 接入 A 股研报(慧博 / 东方财富 / 巨潮)
- [ ] Hacker News 评论摘要 / Reddit r/MachineLearning 舆情
- [ ] 回测引擎(基于 quotes 表 + analyses 信号)
- [ ] 财报日历(下次 earnings call 前 1 周提醒)

## 开发约定

- 新增 collector 都返回 `RawItem`,由 `runner.py` 统一持久化。
- 任何依赖外网的调用都封装在 `collectors/` 或 `analysis/` 内,核心模块不要
  直连 HTTP。
- DB 操作走 `session_scope()`,避免裸 session。
