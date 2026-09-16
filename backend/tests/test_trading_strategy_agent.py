from __future__ import annotations

import asyncio
import json
import unittest

from backend.app.agents import StrategyGenerationError, TradingStrategyAgent
from backend.app.providers import SimulatedMarketDataProvider


INDUSTRIES = [
    {"industry": "算力", "combined_score": 94, "combined_logic": "市场与政策共振", "hot_topics": ["算力升温"], "policy_signals": ["支持政策（预期）"]},
    {"industry": "半导体", "combined_score": 88, "combined_logic": "国产替代关注", "hot_topics": ["芯片热度上升"], "policy_signals": []},
    {"industry": "机器人", "combined_score": 82, "combined_logic": "产业化预期", "hot_topics": ["机器人活跃"], "policy_signals": []},
]
SENTIMENTS = [
    {"industry": "算力", "sentiment": "positive", "sentiment_score": 86, "sentiment_drivers": ["共振"], "risk_factors": ["预期落空"]},
    {"industry": "半导体", "sentiment": "positive", "sentiment_score": 78, "sentiment_drivers": ["关注上升"], "risk_factors": ["需求波动"]},
    {"industry": "机器人", "sentiment": "neutral", "sentiment_score": 58, "sentiment_drivers": ["分歧"], "risk_factors": ["估值波动"]},
]
CAPITAL = [
    {"industry": "算力", "research_rating": "增持", "capital_flow": {"today": "净流入", "five_days": "持续流入", "ten_days": "震荡流入"}, "top_capital_stocks": ["中科曙光", "浪潮信息"]},
    {"industry": "半导体", "research_rating": "增持", "capital_flow": {"today": "净流入", "five_days": "震荡流入", "ten_days": "资金平衡"}, "top_capital_stocks": ["北方华创", "中微公司"]},
    {"industry": "机器人", "research_rating": "中性", "capital_flow": {"today": "资金平衡", "five_days": "震荡流入", "ten_days": "资金平衡"}, "top_capital_stocks": ["三花智控", "拓普集团"]},
]
NETWORK = {
    "core_industries": ["算力"],
    "industry_relations": {
        "算力": {"upstream": ["半导体"], "downstream": [], "related": []},
        "半导体": {"upstream": [], "downstream": ["算力"], "related": []},
        "机器人": {"upstream": [], "downstream": [], "related": []},
    },
    "analysis": "算力为核心，半导体提供上游支撑。",
}


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def complete(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        self.calls.append(user_prompt)
        return self.responses.pop(0)


def selection(*, hallucinate: bool = False) -> str:
    stocks = {"算力": ["中科曙光"], "半导体": ["北方华创"], "机器人": ["三花智控"]}
    if hallucinate:
        stocks["算力"] = ["虚构股票"]
    return json.dumps(
        {
            "market_view": "模拟数据下，行业情绪分化，优先观察高评分且资金配合的方向。",
            "selections": [
                {"industry": name, "stocks": stocks[name], "rationale": f"{name}综合证据相对占优。", "supporting_evidence": ["综合评分与资金趋势"], "risks": ["信号可能失效"]}
                for name in ("算力", "半导体", "机器人")
            ],
            "execution_notes": ["分批执行，不追涨", "第五个交易日重新评估"],
        },
        ensure_ascii=False,
    )


class TradingStrategyAgentTests(unittest.TestCase):
    def test_generates_all_report_sections_and_simulation_metadata(self) -> None:
        agent = TradingStrategyAgent(FakeLLM([selection()]), SimulatedMarketDataProvider())
        result = asyncio.run(
            agent.generate(
                combined_industries=INDUSTRIES,
                industry_network=NETWORK,
                industry_sentiments=SENTIMENTS,
                research_capital=CAPITAL,
                research_metadata={"data_mode": "simulated"},
                as_of_date="2026-08-11",
            )
        )
        report = result["trading_strategy"]
        for section in range(1, 9):
            self.assertIn(f"## {section}.", report)
        self.assertIn("不构成投资建议", report)
        self.assertTrue(result["strategy_metadata"]["is_simulation"])

    def test_hallucinated_stock_is_retried(self) -> None:
        llm = FakeLLM([selection(hallucinate=True), selection()])
        agent = TradingStrategyAgent(llm, SimulatedMarketDataProvider())
        result = asyncio.run(
            agent.generate(
                combined_industries=INDUSTRIES,
                industry_network=NETWORK,
                industry_sentiments=SENTIMENTS,
                research_capital=CAPITAL,
                research_metadata={"data_mode": "simulated"},
                as_of_date="2026-08-11",
            )
        )
        self.assertIn("# 5日短线交易策略报告", result["trading_strategy"])
        self.assertEqual(len(llm.calls), 2)

    def test_trade_plan_never_exceeds_capital_and_uses_board_lots(self) -> None:
        agent = TradingStrategyAgent(FakeLLM([]), SimulatedMarketDataProvider())
        selections = json.loads(selection())["selections"]
        quotes = {
            "中科曙光": {"current_price": 20, "five_day_volatility": 0.03, "lot_size": 100},
            "北方华创": {"current_price": 15, "five_day_volatility": 0.04, "lot_size": 100},
            "三花智控": {"current_price": 10, "five_day_volatility": 0.025, "lot_size": 100},
        }
        plans, reserve = agent.build_trade_plan(selections, quotes)
        self.assertLessEqual(sum(plan.planned_amount for plan in plans), 10_000)
        self.assertAlmostEqual(sum(plan.planned_amount for plan in plans) + reserve, 10_000)
        self.assertTrue(all(plan.shares % 100 == 0 for plan in plans))
        self.assertTrue(all(plan.stop_price < plan.buy_low < plan.target_low for plan in plans))

    def test_requires_three_tradeable_industries(self) -> None:
        agent = TradingStrategyAgent(FakeLLM([]), SimulatedMarketDataProvider())
        with self.assertRaises(StrategyGenerationError):
            asyncio.run(
                agent.generate(
                    combined_industries=INDUSTRIES[:2],
                    industry_network=NETWORK,
                    industry_sentiments=SENTIMENTS[:2],
                    research_capital=CAPITAL[:2],
                    research_metadata={"data_mode": "simulated"},
                    as_of_date="2026-08-11",
                )
            )

    def test_workflow_state_contract(self) -> None:
        agent = TradingStrategyAgent(FakeLLM([selection()]), SimulatedMarketDataProvider())
        update = asyncio.run(
            agent.run(
                {
                    "combined_industries": INDUSTRIES,
                    "industry_network": NETWORK,
                    "industry_sentiments": SENTIMENTS,
                    "industry_research_capital": CAPITAL,
                    "research_capital_metadata": {"data_mode": "simulated"},
                    "analysis_date": "2026-08-11",
                }
            )
        )
        self.assertIn("trading_strategy", update)
        self.assertIn("strategy_metadata", update)


if __name__ == "__main__":
    unittest.main()
