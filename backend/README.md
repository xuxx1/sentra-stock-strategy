# SENTRA 后端

## 模块 1.1：东方财富股吧热门话题

采集器位于 `app/collectors/eastmoney_guba.py`，使用 Python 标准库实现，不需要额外安装采集依赖。

运行：

```powershell
python backend/scripts/fetch_guba_topics.py --pages 1 --page-size 50
```

保存为 JSON：

```powershell
python backend/scripts/fetch_guba_topics.py --output data/guba_topics.json
```

如果匿名访问被限制，可在本地环境中设置 `EASTMONEY_COOKIE`。不要把 Cookie 提交到代码仓库。

标准输出包含：`title`、`content`、`tags`、`url`、`read_count`、`comment_count`、
`favorite_count`、`stocks`、`rank`、`source` 和 `collected_at`。计数字段统一为整数，便于后续排序和计算。

异步工作流调用：

```python
from backend.app.collectors import EastMoneyGubaCollector

topics = await EastMoneyGubaCollector().collect_async(pages=1, page_size=50)
```

测试：

```powershell
python -m unittest backend.tests.test_eastmoney_guba -v
```

该接口不是公开稳定 API，生产环境应限制采集频率、保留原始响应日志，并遵守数据源服务条款。

## 模块 1.2：东方财富财经经济时评

采集器位于 `app/collectors/eastmoney_finance.py`。它解析 `div.tabList ul.h28.fn li`，
默认获取前 10 篇文章，并从详情页的 `div.contentwrap` 提取全文。

```powershell
python backend/scripts/fetch_finance_commentary.py --limit 10
```

持久化去重并保存结果：

```powershell
python backend/scripts/fetch_finance_commentary.py `
  --output data/finance_commentary.json `
  --seen-file data/seen_finance_urls.json
```

工作流异步调用：

```python
from backend.app.collectors import EastMoneyFinanceCollector

articles = await EastMoneyFinanceCollector().collect_async(limit=10, seen_urls=known_urls)
```

输出严格包含 `title`、`time`、`content` 和 `url`。榜单内部去重会清理追踪参数；
传入已抓取 URL 或使用命令行 `--seen-file` 可以实现跨批次去重。详情页最多使用 4 个并发请求，
单篇异常会被跳过，不会中断整个排行榜节点。

## 模块 2.1：股吧行业分析 Agent

Agent 位于 `app/agents/guba_industry.py`，通过 `LLMClient` 协议与具体模型供应商解耦。
节点会先根据阅读、评论、收藏和原始排名计算热度，再把压缩后的前 30 条话题发送给模型。

工作流接口：

```python
from backend.app.agents import GubaIndustryAnalysisAgent

agent = GubaIndustryAnalysisAgent(llm=model_adapter)
state_update = await agent.run({"guba_topics": topics})
# state_update = {"guba_industries": [...]}
```

模型适配器只需实现：

```python
async def complete(*, system_prompt: str, user_prompt: str, temperature: float) -> str:
    ...
```

Agent 强制模型返回结构化 JSON，并最多重试一次格式错误响应。输出中的话题标题和股票名称会与
输入数据交叉校验，模型自行补充的内容将被过滤。股吧原文按不可信输入处理，正文中的提示词不会改变 Agent 任务。

## 模块 2.2：时评行业分析 Agent

Agent 位于 `app/agents/finance_industry.py`，读取财经时评文章并输出宏观因素、政策信号和受益行业。

```python
from backend.app.agents import FinanceIndustryAnalysisAgent

agent = FinanceIndustryAnalysisAgent(llm=model_adapter)
update = await agent.run({"finance_commentary": articles})
# update = {"commentary_industries": [...]}
```

节点默认分析 10 篇文章，每篇正文最多保留 5000 字符，总正文上下文不超过 32000 字符。
提示词要求区分“已落地政策、政策预期和作者观点”；模型输出的宏观因素及政策信号还会与原文进行
文本相关性校验，无原文依据的信号将被过滤。

## 模块 3.1：行业合并分析

融合节点位于 `app/fusion/industry_merger.py`。该节点不调用模型，使用固定公式生成可复现的综合榜单：

- 市场热度权重：55%
- 政策支持权重：45%
- 同时获得市场和政策支持：额外 8 分共振加分
- 单项得分由上游排名、话题/政策证据数量及重复提名共同决定

```python
from backend.app.fusion import IndustryFusionNode

node = IndustryFusionNode()
update = await node.run({
    "guba_industries": guba_industries,
    "commentary_industries": commentary_industries,
})
# update = {"combined_industries": [...]}
```

节点内置常见别名，例如 `AI 算力板块`、`算力概念`、`算力基础设施` 会统一为 `算力`。
可以通过构造参数 `aliases` 增加项目自己的行业映射，也可以调整两个权重和共振加分。

## 模块 4.1：行业关联网络构建 Agent

Agent 位于 `app/agents/industry_network.py`，读取综合行业榜单并输出上下游、横向关联和核心行业。

```python
from backend.app.agents import IndustryNetworkAgent

agent = IndustryNetworkAgent(llm=model_adapter)
update = await agent.run({"combined_industries": combined_industries})
# update = {"industry_network": {...}}
```

为保证图谱可追溯，模型只能使用综合榜单中已有的行业，不允许添加外部节点。节点会过滤自环和未知行业，
自动补齐 `A.upstream = B` 对应的 `B.downstream = A`，并将横向 `related` 关系处理成双向关系。
当模型没有给出有效核心行业时，系统根据综合评分和节点连接度自动选择核心节点。

## 模块 5.1：行业情绪分析 Agent

Agent 位于 `app/agents/industry_sentiment.py`，综合行业榜单和关联网络，为每个行业生成情绪方向、
情绪分数、驱动因素和风险因素。

```python
from backend.app.agents import IndustrySentimentAgent

agent = IndustrySentimentAgent(llm=model_adapter)
update = await agent.run({
    "combined_industries": combined_industries,
    "industry_network": industry_network,
})
# update = {"industry_sentiments": [...]}
```

`sentiment_score` 是方向分，而非独立的绝对强度：0–39 为 `negative`，40–60 为 `neutral`，
61–100 为 `positive`。节点会验证标签与分数一致，并要求综合榜单中的每个行业都有结果；缺失行业、
非法分数或标签冲突都会触发模型重试。

## 模块 6.1：研报与资金流数据整合 Agent

Agent 位于 `app/agents/research_capital.py`，数据提供器协议及模拟实现位于
`app/providers/research_capital.py`。当前模拟数据按照“行业 + 分析日期”确定性生成，相同输入会得到相同结果。

```python
from backend.app.agents import ResearchCapitalAgent
from backend.app.providers import SimulatedResearchCapitalProvider

agent = ResearchCapitalAgent(llm=model_adapter, provider=SimulatedResearchCapitalProvider())
update = await agent.run({
    "industry_sentiments": industry_sentiments,
    "analysis_date": "2026-08-11",
})
```

工作流除 `industry_research_capital` 外，还返回 `research_capital_metadata`。模拟模式下其中包含
`data_mode: simulated` 和警告文本，前端必须明显展示该标识。资金流标签由数值确定性计算，模型只能复制；
模型输出的龙头股票必须来自数据提供器候选范围。未知行业不会自动生成虚构股票。

## 模块 7.1：5 日交易策略生成 Agent

Agent 位于 `app/agents/trading_strategy.py`，行情提供器位于 `app/providers/market_data.py`。
由于上游研报资金节点没有股票价格，策略节点必须额外注入行情提供器；开发阶段使用
`SimulatedMarketDataProvider`，以后可以替换为真实行情实现。

```python
from backend.app.agents import TradingStrategyAgent
from backend.app.providers import SimulatedMarketDataProvider

agent = TradingStrategyAgent(llm=model_adapter, market_provider=SimulatedMarketDataProvider())
update = await agent.run(workflow_state)
```

模型只负责选择 3 个行业、每个行业 1–2 只候选股票，以及生成观点、依据和风险。程序负责：

- 校验行业与股票均来自上游候选范围；
- 按 40% / 33% / 27% 分配三个行业预算；
- 按 A 股整手数量计算可买股数；
- 根据模拟现价和 5 日波动率计算关注区间、目标区间及风险退出价；
- 确保计划金额不超过 1 万元，并保留无法整手使用的现金；
- 将目标区间换算为情景收益区间，而非收益承诺。

输出除 `trading_strategy` Markdown 报告外，还包含 `strategy_metadata`。模拟模式会明确标识并在报告中显示风险提示。

## 启动完整 API 与前端接入

后端 API 不需要安装额外 Python 包：

```powershell
$env:OPENAI_API_KEY="你的后端密钥"
$env:OPENAI_MODEL="gpt-5.6-luna"
python backend/server.py --host 127.0.0.1 --port 8000
```

密钥只能设置在后端环境变量中，不能写入前端。支持的接口：

- `GET /api/health`：服务和模型配置状态；
- `GET /api/workflow/latest`：最近一次运行结果；
- `POST /api/collect`：真实并行采集股吧和财经时评；
- `POST /api/workflow/analyze`：分析最近一次采集数据并生成策略；
- `POST /api/workflow/run`：从真实采集到策略报告的一键全链路。

前端默认连接 `http://127.0.0.1:8000`。如需调整，在前端运行环境设置：

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

研报资金与行情仍使用明确标记的模拟提供器；股吧和财经文章由采集按钮真实请求。更换真实资金或行情时，
实现 `ResearchCapitalProvider` 或 `MarketDataProvider` 协议并在 `PipelineService` 中替换即可。
