# AI 产业投资情报系统 (`intel`)

一个聚焦**全球 AI 产业**的命令行投研情报系统:从公开数据源自动采集
新闻 / 研报 / 论文 / 监管披露 / 行情,再用 Claude 完成中文摘要、影响评估
和每日简报,数据全部落本地 SQLite。

## 设计目标

| 模块 | 内容 |
| --- | --- |
| 资产范围 | 全球 AI 产业链(芯片 / 云 / 模型实验室 / 应用 / 监管) |
| 数据源 | RSS、arXiv、Hacker News、SEC EDGAR、yfinance |
| 形式 | CLI(`intel`) + 本地 SQLite |
| 智能层 | Anthropic Claude(Haiku 做单条三审,Sonnet 做综合简报),启用 prompt caching |

## 目录结构

```
src/intel/
├── cli/main.py              # typer CLI 入口
├── collectors/              # rss / arxiv / hackernews / sec_edgar / quotes
│   └── runner.py            # 统一调度,幂等写库
├── analysis/
│   ├── llm.py               # Anthropic SDK 封装(prompt caching)
│   └── pipeline.py          # 调度未分析新闻 + 生成 digest
├── storage/                 # SQLAlchemy ORM + 仓储函数
└── config/
    ├── companies.yaml       # 跟踪标的清单(可改)
    ├── sources.yaml         # 数据源清单(可改)
    └── settings.py          # 读 .env 的运行配置
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
intel collect                      # 跑全部数据源
intel collect --kind rss           # 只跑 RSS
intel collect --kind sec_edgar     # 抓 EDGAR 备案
intel collect --kind yfinance      # 抓行情(默认不跑)

intel latest --hours 12            # 最近 12 小时新闻
intel search "blackwell"           # 关键字搜
intel company NVDA                 # 看单公司情报
intel companies                    # 看跟踪清单

intel analyze --limit 50           # 分析未处理新闻
intel digest --hours 24            # 当日简报
intel digest --hours 168 --period weekly  # 周报
```

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

- [ ] 增加 RSS 翻译(英文新闻直接生成中文摘要,目前已通过 system prompt 强制中文)
- [ ] 接入 a 股研报(慧博 / 东方财富 / 巨潮)
- [ ] Hacker News 评论摘要 / Reddit r/MachineLearning 舆情
- [ ] Telegram / 邮件推送 digest
- [ ] 简单的事件驱动告警(财报、监管、CEO 离职)

## 开发约定

- 新增 collector 都返回 `RawItem`,由 `runner.py` 统一持久化。
- 任何依赖外网的调用都封装在 `collectors/` 或 `analysis/` 内,核心模块不要
  直连 HTTP。
- DB 操作走 `session_scope()`,避免裸 session。
