# TradingAgents-Astock 代码结构

## 整体架构

```
用户输入(CLI/Web) → TradingAgentsGraph → 7个分析师 → 质量审核 → 多空辩论 → 交易员 → 风控辩论 → PM最终决策
```

| 目录 | 作用 |
|---|---|
| `main.py` | 示例入口，用 yfinance 跑美股 |
| `cli/main.py` | Typer + Rich CLI 交互入口 |
| `web/` | Streamlit Web UI + PDF 导出 |
| `tradingagents/dataflows/` | 数据层：vendor 路由 + A股/Yahoo/Alpha Vantage 实现 |
| `tradingagents/agents/` | Agent 层：7个分析师 + 辩论 + 交易员 + 风控 + PM |
| `tradingagents/graph/` | LangGraph 编排层 |
| `tests/` | 测试套件 |

---

## 1. 股票数据 & 新闻获取链路

### 1.1 路由层 — `tradingagents/dataflows/interface.py`

一切数据调用的**唯一入口**：

```python
# 所有 LLM tool call 最终走到这里
route_to_vendor(method, *args, **kwargs)
```

- 读配置 `data_vendors` → 确定该类别用哪个 vendor
- 按 `VENDOR_METHODS` 字典找到对应实现函数
- 主 vendor 失败 → 自动降级尝试其他 vendor

**17 个 method**，分 5 个类别：

| 类别 | 方法 |
|---|---|
| `core_stock_apis` | `get_stock_data` |
| `technical_indicators` | `get_indicators` |
| `fundamental_data` | `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` |
| `news_data` | `get_news`, `get_global_news`, `get_insider_transactions` |
| `signal_data` | `get_profit_forecast`, `get_hot_stocks`, `get_northbound_flow`, `get_concept_blocks`, `get_fund_flow`, `get_dragon_tiger_board`, `get_lockup_expiry`, `get_industry_comparison` |

### 1.2 A 股数据 Vendor — `tradingagents/dataflows/a_stock.py` (~1995行)

零第三方数据库依赖，纯 HTTP 直连 + mootdx TCP。

| 方法 | 数据来源 | 说明 |
|---|---|---|
| `get_stock_data` | mootdx TCP 7709 → 新浪 fallback | OHLCV K线 |
| `get_indicators` | stockstats 库（基于 mootdx K线） | MACD/RSI/布林带等 13 种指标 |
| `get_fundamentals` | 腾讯财经 + mootdx + 东财 + 同花顺 | PE/PB/市值/换手率 |
| `get_balance_sheet` | 新浪财经 HTTP | 资产负债表 |
| `get_cashflow` | 新浪财经 HTTP | 现金流量表 |
| `get_income_statement` | 新浪财经 HTTP | 利润表 |
| `get_news` | 东财 np-weblist → 新浪 fallback | 个股新闻 |
| `get_global_news` | 财联社 cls.cn + 东财 global | 宏观财经快讯 |
| `get_insider_transactions` | mootdx F10 股东研究 | 内部交易/股东持股变动 |
| `get_profit_forecast` | 同花顺 10jqka | EPS 一致预期/前向 PE/PEG |
| `get_hot_stocks` | 同花顺 | 涨停股 + 题材标签 + 热度排序 |
| `get_northbound_flow` | 同花顺 hsgtApi + CSV 缓存 | 北向资金实时 + 历史 |
| `get_concept_blocks` | 百度股市通 | 概念板块归属 |
| `get_fund_flow` | 东财 push2 | 分钟级 + 日级资金流(大小单) |
| `get_dragon_tiger_board` | 东财 datacenter | 龙虎榜上榜记录 + 席位明细 |
| `get_lockup_expiry` | 东财 datacenter | 历史 + 未来 90 天限售解禁日历 |
| `get_industry_comparison` | 东财 push2 | 同行业排名(90 个申万行业) |

### 1.3 数据来源汇总

| 来源 | 协议 | 数据 |
|---|---|---|
| mootdx | TCP 7709 | OHLCV K线、财务快照、F10 文本 |
| 腾讯财经 | HTTP (qt.gtimg.cn) | PE/PB/市值/换手率 |
| 东方财富 datacenter | HTTP | 龙虎榜、限售解禁、板块行情 |
| 东方财富 push2/push2his | HTTP | 实时行情、个股信息、板块列表、资金流 |
| 东方财富 np-weblist | HTTP | 滚动新闻 |
| 新浪财经 | HTTP | K线历史、财报三表 |
| 同花顺 10jqka | HTTP | EPS 一致预期、热股题材、北向资金 |
| 财联社 cls.cn | HTTP | 全球财经快讯 |
| 百度股市通 | HTTP | 概念板块归属 |

### 1.4 Ticker 解析 — `tradingagents/dataflows/utils.py`

```python
safe_ticker_component(value)
  → resolve_ticker("沪电股份")   # 中文名 → 6位代码
    → _build_name_code_map()    # mootdx 全市场映射, 内存缓存
```

---

## 2. Agent & Tool 调用链路

### 2.1 Tool 定义层 — `tradingagents/agents/utils/`

所有 tool 都是 LangChain `@tool` 装饰的薄包装，只做一件事：调用 `route_to_vendor`。

| 文件 | 包含的 Tool |
|---|---|
| `core_stock_tools.py` | `get_stock_data` |
| `technical_indicators_tools.py` | `get_indicators` |
| `fundamental_data_tools.py` | `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` |
| `news_data_tools.py` | `get_news`, `get_global_news`, `get_insider_transactions` |
| `signal_data_tools.py` | 8 个 A 股特有 signal tool |

典型代码（每个 tool 就 5-10 行）：
```python
@tool
def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """获取 A 股历史 K 线数据，返回 OHLCV。"""
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)
```

### 2.2 7 位分析师 — `tradingagents/agents/analysts/`

统一模式：`create_*_analyst(llm)` → 绑定 tools → 编写中文系统提示词 → 返回 LangGraph node。

| 分析师 | 文件 | 绑定的 Tools | 输出字段 | A 股特化关注点 |
|---|---|---|---|---|
| 技术分析 | `market_analyst.py` | `get_stock_data`, `get_indicators` | `market_report` | T+1, 涨跌停, 量比, 50/200 SMA, RSI, 布林带 |
| 市场情绪 | `social_media_analyst.py` | `get_news` | `sentiment_report` | 东方财富股吧, 散户情绪 |
| 新闻舆情 | `news_analyst.py` | `get_news`, `get_global_news` | `news_report` | 政策敏感性, 信源加权, 板块轮动 |
| 基本面 | `fundamentals_analyst.py` | `get_fundamentals`, 三表, `get_profit_forecast`, `get_industry_comparison` | `fundamentals_report` | CAS 准则, PE 30-50x 估值区间, 商誉减值, 股权质押 |
| 政策分析 | `policy_analyst.py` | `get_news`, `get_global_news` | `policy_report` | 证监会/国务院/产业/货币政策 |
| 游资追踪 | `hot_money_tracker.py` | 9 种 signal tool | `hot_money_report` | 量价异动, 龙虎榜席位, 北向资金, 主力资金流 |
| 解禁监控 | `lockup_watcher.py` | `get_insider_transactions`, `get_lockup_expiry`, `get_fundamentals`, `get_news` | `lockup_report` | 解禁类型, 减持规则 |

### 2.3 质量审核 — `tradingagents/agents/quality_gate.py`

分析师和辩论之间的关卡，两层校验：
1. **硬校验**：报告长度 ≥ 200 字、无失败标记、有数据表格
2. **LLM 审核**：一次性审核 7 份报告的时效性、完整性、可靠性 → 写 `data_quality_summary`

### 2.4 辩论阶段

| 角色 | 文件 | 职责 |
|---|---|---|
| Bull Researcher | `bull_researcher.py` | 构建多方论点：政策红利、北向资金、前向 PE 消化 |
| Bear Researcher | `bear_researcher.py` | 构建空方论点：技术背离、解禁压力、T+1 陷阱 |
| Research Manager | `research_manager.py` | 审阅双方论点 → 输出结构化 `ResearchPlan`（Buy/Overweight/Hold/Underweight/Sell） |

### 2.5 交易员 — `trader.py`

输出结构化 `TraderProposal`：
- `action`: Buy / Hold / Sell
- `reasoning`: 决策逻辑
- `entry_price`: 入场价位
- `stop_loss`: 止损位
- `position_sizing`: 仓位建议

### 2.6 风控辩论

| 角色 | 文件 | 视角 |
|---|---|---|
| Aggressive Debator | `aggressive_debator.py` | 看多：涨停动量、政策底、游资信心 |
| Conservative Debator | `conservative_debator.py` | 看空：T+1 锁仓、跌停风险、解禁压顶 |
| Neutral Debator | `neutral_debator.py` | 中性：仓位管理优先、估值区间交易 |

### 2.7 Portfolio Manager — `portfolio_manager.py`

最终决策者，输出 `PortfolioDecision`：
- `rating`: Buy / Overweight / Hold / Underweight / Sell
- `executive_summary`: 核心结论
- `investment_thesis`: 投资逻辑
- `price_target`: 目标价
- `time_horizon`: 时间维度

### 2.8 结构化输出机制 — `tradingagents/agents/utils/structured.py`

```python
invoke_structured_or_freetext(structured_llm, plain_llm, prompt, render, agent_name)
```
先尝试 `with_structured_output(schema)` → 失败则降级为自由文本 + `parse_rating()` 提取评级。

---

## 3. Graph 编排 — `tradingagents/graph/`

### 3.1 完整流程

```
START
  → [Analyst 1] → [tools node] → [MsgClear] → [Analyst 2] → ...
  → (7 个分析师串联执行)
  → Quality Gate
  → Bull Researcher ⇄ Bear Researcher (多空辩论, max_debate_rounds 轮)
  → Research Manager (结构化 ResearchPlan)
  → Trader (结构化 TraderProposal)
  → Aggressive ⇄ Conservative ⇄ Neutral (风控辩论)
  → Portfolio Manager (结构化 PortfolioDecision)
  → END
```

### 3.2 核心文件

| 文件 | 职责 |
|---|---|
| `trading_graph.py` | `TradingAgentsGraph` 主类：组装 LLM/Tools/Memory/Graph |
| `setup.py` | `GraphSetup.setup_graph()`：构建 LangGraph StateGraph |
| `conditional_logic.py` | 条件路由：tool_calls? → 继续 tools；否则 → 下一个节点 |
| `propagation.py` | `Propagator.create_initial_state()`：初始化 AgentState |
| `reflection.py` | 历史决策复盘：方向性判断 + 经验教训 |
| `signal_processing.py` | 从 PM 决策中提取 Buy/Hold/Sell |
| `checkpointer.py` | SQLite 断点续传，支持中断后恢复 |

---

## 4. 完整调用链路示意

```
用户输入 "002463 沪电股份"
  │
  ▼
cli/main.py (Typer CLI) 或 web/app.py (Streamlit)
  │
  ▼
TradingAgentsGraph.propagate(ticker="002463", trade_date="2026-05-24")
  │
  ├─ 1. 组件创建
  │    create_llm_client() → deep_think_llm + quick_think_llm
  │    create_*_analyst(llm) × 7
  │    ToolNode(tools) × 7 类
  │
  ├─ 2. Graph 编排
  │    Propagator.create_initial_state() → AgentState
  │    GraphSetup.setup_graph() → Compile StateGraph
  │
  ├─ 3. 分析师阶段 (LLM 调 tool → 拿数据 → 写报告)
  │    Market Analyst:
  │      └─ LLM: tool_call → get_stock_data("002463", ...)
  │         └─ route_to_vendor("get_stock_data", ...)
  │            └─ a_stock.get_stock_data() → mootdx TCP → OHLCV
  │      └─ LLM: tool_call → get_indicators(...)
  │         └─ route_to_vendor("get_indicators", ...)
  │            └─ a_stock.get_indicators() → stockstats → MACD / RSI
  │      └─ LLM → 写技术分析报告 → node 返回 market_report
  │    ... (其余 6 个分析师同理)
  │
  ├─ 4. 辩论 + 决策阶段
  │    Quality Gate → Bull/Bear 辩论 → Research Manager → Trader
  │    → Aggressive/Conservative/Neutral 风控辩论 → Portfolio Manager
  │
  └─ 5. 输出
      ├─ full_states_log_*.json (写入 ~/.tradingagents/logs/)
      ├─ Memory Log (延迟复盘，下次运行时触发)
      ├─ CLI: Rich 终端实时展示
      └─ Web: Streamlit UI + PDF 下载
```
