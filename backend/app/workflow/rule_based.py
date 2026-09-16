"""无需大模型的确定性分析引擎。

该引擎用于未配置云端模型、或模型调用临时失败时的兜底路径。所有判断均可
由关键词、热度公式和输入数据回放，不把规则结果描述成大模型结论。
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping, Sequence

from backend.app.agents import ResearchCapitalAgent, TradingStrategyAgent
from backend.app.fusion import IndustryFusionNode
from backend.app.providers import SimulatedMarketDataProvider, SimulatedResearchCapitalProvider


class _UnusedLLM:
    async def complete(self, **_: Any) -> str:  # pragma: no cover - 防止误调用
        raise RuntimeError("纯规则模式不应调用大模型")


class RuleBasedAnalysisEngine:
    """将采集结果转换为完整的行业、情绪、资金和策略结果。"""

    TAXONOMY: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("机器人", ("机器人", "人形", "宇树", "自动化", "智能制造", "机器视觉")),
        ("算力", ("算力", "人工智能", "ai", "服务器", "数据中心", "英伟达", "光通信", "cpo")),
        ("半导体", ("半导体", "芯片", "集成电路", "存储", "光刻", "mlcc", "电子元件")),
        ("新能源车", ("新能源车", "电动车", "锂电", "电池", "充电桩", "智能汽车")),
        ("医药", ("医药", "创新药", "减肥药", "glp-1", "cro", "制药", "医疗")),
        ("能源", ("能源", "原油", "油价", "煤炭", "天然气", "光伏", "储能")),
        ("消费", ("消费", "家电", "食品饮料", "零售", "白酒", "旅游")),
        ("银行", ("银行", "金融", "降息", "降准", "信贷")),
        ("军工", ("军工", "国防", "航空", "航天", "卫星", "无人机")),
    )
    POLICY_WORDS = ("政策", "支持", "规划", "补贴", "降息", "降准", "国产替代", "出海", "投资", "建设", "发展")
    MACRO_WORDS = ("通胀", "利率", "汇率", "经济增长", "需求", "出口", "油价", "流动性")
    NEGATIVE_WORDS = ("下跌", "抛售", "风险", "承压", "下调", "收紧", "亏损", "减持")

    def __init__(
        self,
        *,
        research_provider: Any | None = None,
        market_provider: Any | None = None,
    ) -> None:
        self.research_provider = research_provider or SimulatedResearchCapitalProvider()
        self.market_provider = market_provider or SimulatedMarketDataProvider()

    async def run(self, state: Mapping[str, Any]) -> dict[str, Any]:
        topics = self._records(state.get("guba_topics"))
        articles = self._records(state.get("finance_commentary"))
        market = self.analyze_topics(topics)
        policy = self.analyze_commentary(articles)
        combined = IndustryFusionNode().merge(market, policy)
        if len(combined) < 3:
            raise ValueError("纯规则模式至少需要识别出 3 个行业，请增加采集数据后重试")

        network = self.build_network(combined)
        sentiments = self.analyze_sentiment(combined, network, topics, articles)
        capital, capital_metadata = await self.integrate_research_capital(
            sentiments, str(state.get("analysis_date") or "")
        )
        strategy = await self.generate_strategy(
            combined, network, sentiments, capital, capital_metadata,
            str(state.get("analysis_date") or ""),
        )
        return {
            "guba_industries": market,
            "commentary_industries": policy,
            "combined_industries": combined,
            "industry_network": network,
            "industry_sentiments": sentiments,
            "industry_research_capital": capital,
            "research_capital_metadata": capital_metadata,
            **strategy,
        }

    def analyze_topics(self, topics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        evidence: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"score": 0.0, "topics": [], "stocks": []}
        )
        for raw in topics:
            title = self._text(raw.get("title"), 180)
            content = self._text(raw.get("content"), 800)
            stock_names = [
                self._text(item.get("name"), 50)
                for item in self._records(raw.get("stocks"))
            ]
            haystack = f"{title} {content} {' '.join(stock_names)}".lower()
            engagement = math.log10(
                max(10, self._number(raw.get("read_count")) + self._number(raw.get("comment_count")) * 20)
            )
            for industry, keywords in self.TAXONOMY:
                hits = sum(keyword.lower() in haystack for keyword in keywords)
                if not hits:
                    continue
                item = evidence[industry]
                item["score"] += engagement * (1 + min(2, hits - 1) * 0.2)
                self._append_unique(item["topics"], title, 6)
                for stock in stock_names:
                    self._append_unique(item["stocks"], stock, 8)

        ranked = sorted(evidence.items(), key=lambda pair: (-pair[1]["score"], pair[0]))
        return [
            {
                "industry": industry,
                "logic": f"规则识别到 {len(item['topics'])} 个高热话题，依据阅读、评论和关键词命中综合排序。",
                "hot_topics": item["topics"],
                "related_stocks": item["stocks"],
            }
            for industry, item in ranked[:12]
        ]

    def analyze_commentary(self, articles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        evidence: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"score": 0, "signals": [], "macro": [], "titles": []}
        )
        for raw in articles:
            title = self._text(raw.get("title"), 180)
            content = self._text(raw.get("content"), 5_000)
            haystack = f"{title} {content}".lower()
            signals = [word for word in self.POLICY_WORDS if word in haystack]
            macros = [word for word in self.MACRO_WORDS if word in haystack]
            for industry, keywords in self.TAXONOMY:
                hits = sum(keyword.lower() in haystack for keyword in keywords)
                if not hits:
                    continue
                item = evidence[industry]
                item["score"] += hits * 3 + len(signals) * 2 + len(macros)
                self._append_unique(item["titles"], title, 5)
                for signal in signals:
                    self._append_unique(item["signals"], f"文章出现“{signal}”信号", 6)
                for macro in macros:
                    self._append_unique(item["macro"], macro, 6)

        ranked = sorted(evidence.items(), key=lambda pair: (-pair[1]["score"], pair[0]))
        return [
            {
                "industry": industry,
                "logic": f"规则从财经时评中识别到 {len(item['titles'])} 篇相关内容，政策信号需结合正式文件复核。",
                "macro_factors": item["macro"] or ["市场需求"],
                "policy_signals": item["signals"] or ["未识别到明确政策词，按行业相关性计分"],
            }
            for industry, item in ranked[:12]
        ]

    def build_network(self, combined: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        names = [self._text(item.get("industry"), 50) for item in combined]
        known = {
            "算力": {"upstream": ["半导体", "能源"], "downstream": ["机器人", "新能源车"], "related": ["数据中心"]},
            "半导体": {"upstream": ["能源"], "downstream": ["算力", "机器人", "新能源车"], "related": ["军工"]},
            "机器人": {"upstream": ["半导体", "算力"], "downstream": ["消费", "新能源车"], "related": ["军工"]},
            "新能源车": {"upstream": ["半导体", "能源"], "downstream": ["消费"], "related": ["机器人"]},
            "医药": {"upstream": [], "downstream": ["消费"], "related": []},
            "能源": {"upstream": [], "downstream": ["半导体", "算力", "新能源车"], "related": []},
            "消费": {"upstream": ["新能源车", "医药"], "downstream": [], "related": ["银行"]},
            "银行": {"upstream": [], "downstream": ["消费", "新能源车"], "related": []},
            "军工": {"upstream": ["半导体", "能源"], "downstream": [], "related": ["机器人"]},
        }
        relations: dict[str, dict[str, list[str]]] = {}
        for name in names:
            source = known.get(name, {"upstream": [], "downstream": [], "related": []})
            relations[name] = {
                key: [value for value in source[key] if value in names]
                for key in ("upstream", "downstream", "related")
            }
        core = names[: min(3, len(names))]
        return {
            "core_industries": core,
            "industry_relations": relations,
            "analysis": f"规则网络将 {'、'.join(core)} 识别为当前高分核心；产业链关系来自预设行业映射，需结合最新基本面复核。",
        }

    def analyze_sentiment(
        self,
        combined: Sequence[Mapping[str, Any]],
        network: Mapping[str, Any],
        topics: Sequence[Mapping[str, Any]],
        articles: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        all_text = " ".join(
            self._text(item.get("title"), 180) + " " + self._text(item.get("content"), 1_000)
            for item in [*topics, *articles]
        ).lower()
        core = set(network.get("core_industries", []))
        result: list[dict[str, Any]] = []
        for item in combined:
            industry = self._text(item.get("industry"), 50)
            score = round(
                self._number(item.get("combined_score")) * 0.72
                + (8 if industry in core else 3)
                - min(12, sum(all_text.count(word) for word in self.NEGATIVE_WORDS))
            )
            score = max(20, min(95, score))
            sentiment = "positive" if score >= 62 else "negative" if score <= 39 else "neutral"
            drivers = [
                f"综合行业评分 {round(self._number(item.get('combined_score')))}",
                "进入规则网络核心" if industry in core else "行业热度与政策词共同计分",
            ]
            result.append(
                {
                    "industry": industry,
                    "sentiment": sentiment,
                    "sentiment_score": score,
                    "sentiment_drivers": drivers,
                    "risk_factors": ["关键词热度可能快速衰减", "规则判断不等同于基本面结论"],
                }
            )
        return result

    async def integrate_research_capital(
        self, sentiments: Sequence[Mapping[str, Any]], analysis_date: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        names = [self._text(item.get("industry"), 50) for item in sentiments]
        raw = await self.research_provider.fetch(names, as_of_date=analysis_date)
        sentiment_map = {self._text(item.get("industry"), 50): item for item in sentiments}
        result: list[dict[str, Any]] = []
        for name in names:
            item = raw.get(name, {})
            flows = list(item.get("daily_net_inflow_million", []))
            stocks = sorted(
                self._records(item.get("stock_capital_flows")),
                key=lambda value: -self._number(value.get("today_net_inflow_million")),
            )
            sentiment_score = self._number(sentiment_map[name].get("sentiment_score"))
            rating = "买入" if sentiment_score >= 82 else "增持" if sentiment_score >= 62 else "中性" if sentiment_score >= 42 else "减持"
            result.append(
                {
                    "industry": name,
                    "research_rating": rating,
                    "capital_flow": ResearchCapitalAgent.classify_capital_flow(flows),
                    "top_capital_stocks": [self._text(stock.get("name"), 50) for stock in stocks[:2]],
                }
            )
        return result, {
            "data_mode": self.research_provider.data_mode,
            "analysis_mode": "rule_based",
            "as_of_date": analysis_date,
            "warning": "研报与资金流为模拟数据" if self.research_provider.data_mode == "simulated" else "资金流来自东方财富真实数据；研报仍为模拟。行业判断来自纯规则模式，不构成投资建议。",
        }

    async def generate_strategy(
        self,
        combined: Sequence[Mapping[str, Any]],
        network: Mapping[str, Any],
        sentiments: Sequence[Mapping[str, Any]],
        capital: Sequence[Mapping[str, Any]],
        metadata: Mapping[str, Any],
        analysis_date: str,
    ) -> dict[str, Any]:
        agent = TradingStrategyAgent(_UnusedLLM(), self.market_provider)
        context = agent.prepare_context(combined, network, sentiments, capital, metadata)
        eligible = context["eligible_industries"][:3]
        if len(eligible) < 3:
            raise ValueError("纯规则模式未获得至少 3 个可交易行业的模拟股票池")
        selections = []
        for item in eligible:
            selections.append(
                {
                    "industry": item["industry"],
                    "stocks": item["candidate_stocks"][:1],
                    "rationale": f"综合分 {item['combined_score']}、情绪分 {item['sentiment_score']}，按规则排序进入前三。",
                    "supporting_evidence": ["行业综合评分", "情绪强度", "模拟资金流趋势"],
                    "risks": item["risk_factors"] or ["规则信号可能失效"],
                }
            )
        selection = {
            "market_view": "纯规则模式显示市场热点分化，优先观察综合评分、情绪和模拟资金趋势相对占优的行业。",
            "selections": selections,
            "execution_notes": ["分批挂单，避免追涨", "触及止损严格退出", "第 5 个交易日重新评估全部信号"],
        }
        stocks = [stock for item in selections for stock in item["stocks"]]
        quotes = await self.market_provider.fetch_quotes(stocks, as_of_date=analysis_date)
        plans, reserve = agent.build_trade_plan(selections, quotes)
        simulated = (
            self.market_provider.data_mode == "simulated"
            or self.research_provider.data_mode == "simulated"
        )
        report = agent.render_report(
            selection, context, plans, reserve, analysis_date, simulated=simulated
        )
        return {
            "trading_strategy": report,
            "strategy_metadata": {
                "as_of_date": analysis_date,
                "total_capital": agent.total_capital,
                "market_data_mode": self.market_provider.data_mode,
                "research_capital_mode": self.research_provider.data_mode,
                "analysis_mode": "rule_based",
                "is_simulation": simulated,
                "recommendations": selections,
                "trade_plans": [agent._plan_dict(plan) for plan in plans],
                "cash_reserve": reserve,
                "warning": "纯规则分析及模拟行情结果仅用于系统演示与研究，不构成投资建议。" if simulated else "策略使用真实行情数据生成；仅用于研究，不构成投资建议。",
            },
        }

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return []
        return [item for item in value if isinstance(item, Mapping)]

    @staticmethod
    def _text(value: Any, limit: int) -> str:
        return " ".join(str(value or "").replace("\x00", " ").split())[:limit]

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError, OverflowError):
            return 0.0

    @staticmethod
    def _append_unique(target: list[str], value: str, limit: int) -> None:
        if value and value not in target and len(target) < limit:
            target.append(value)
