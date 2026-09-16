from __future__ import annotations

import asyncio
import json
import unittest

from backend.app.agents import ResearchCapitalAgent
from backend.app.providers import SimulatedResearchCapitalProvider


SENTIMENTS = [
    {
        "industry": "算力",
        "sentiment": "positive",
        "sentiment_score": 85,
        "sentiment_drivers": ["市场与政策预期共振"],
        "risk_factors": ["政策预期未兑现"],
    },
    {
        "industry": "未知细分行业",
        "sentiment": "neutral",
        "sentiment_score": 50,
        "sentiment_drivers": ["多空分歧"],
        "risk_factors": [],
    },
]


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> str:
        self.calls.append(user_prompt)
        return self.responses.pop(0)


def build_response(inputs: list[dict], *, invalid_flow: bool = False, unknown_stock: bool = False) -> str:
    values = []
    for item in inputs:
        flow = dict(item["expected_capital_flow"])
        if invalid_flow and item["industry"] == "算力":
            flow["today"] = "净流出" if flow["today"] != "净流出" else "净流入"
        candidates = [stock["name"] for stock in item["candidate_stocks"][:2]]
        if unknown_stock and item["industry"] == "算力":
            candidates.append("虚构股票")
        values.append(
            {
                "industry": item["industry"],
                "research_rating": "增持",
                "capital_flow": flow,
                "top_capital_stocks": candidates,
            }
        )
    return json.dumps(values, ensure_ascii=False)


class ResearchCapitalAgentTests(unittest.TestCase):
    def _prepared(self) -> tuple[ResearchCapitalAgent, list[dict]]:
        provider = SimulatedResearchCapitalProvider()
        agent = ResearchCapitalAgent(FakeLLM([]), provider)
        sentiments = agent.prepare_sentiments(SENTIMENTS)
        data = asyncio.run(provider.fetch([item["industry"] for item in sentiments], as_of_date="2026-08-11"))
        return agent, agent.prepare_provider_data(sentiments, data)

    def test_simulation_is_deterministic_and_unknown_industry_has_no_fake_stocks(self) -> None:
        provider = SimulatedResearchCapitalProvider()
        first = asyncio.run(provider.fetch(["算力", "未知细分行业"], as_of_date="2026-08-11"))
        second = asyncio.run(provider.fetch(["算力", "未知细分行业"], as_of_date="2026-08-11"))
        self.assertEqual(first, second)
        self.assertEqual(first["未知细分行业"]["stock_capital_flows"], [])
        self.assertEqual(first["算力"]["data_mode"], "simulated")

    def test_validates_computed_capital_flow_and_stock_scope(self) -> None:
        base_agent, inputs = self._prepared()
        agent = ResearchCapitalAgent(FakeLLM([build_response(inputs)]), base_agent.provider)
        results, metadata = asyncio.run(agent.analyze(SENTIMENTS, as_of_date="2026-08-11"))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["capital_flow"], inputs[0]["expected_capital_flow"])
        self.assertEqual(results[1]["top_capital_stocks"], [])
        self.assertEqual(metadata["data_mode"], "simulated")

    def test_incorrect_flow_label_is_retried(self) -> None:
        base_agent, inputs = self._prepared()
        llm = FakeLLM([build_response(inputs, invalid_flow=True), build_response(inputs)])
        agent = ResearchCapitalAgent(llm, base_agent.provider)
        results, _ = asyncio.run(agent.analyze(SENTIMENTS, as_of_date="2026-08-11"))
        self.assertEqual(len(results), 2)
        self.assertEqual(len(llm.calls), 2)

    def test_hallucinated_stock_is_retried(self) -> None:
        base_agent, inputs = self._prepared()
        llm = FakeLLM([build_response(inputs, unknown_stock=True), build_response(inputs)])
        agent = ResearchCapitalAgent(llm, base_agent.provider)
        results, _ = asyncio.run(agent.analyze(SENTIMENTS, as_of_date="2026-08-11"))
        self.assertEqual(len(results), 2)
        self.assertEqual(len(llm.calls), 2)

    def test_workflow_returns_visible_data_mode(self) -> None:
        base_agent, inputs = self._prepared()
        agent = ResearchCapitalAgent(FakeLLM([build_response(inputs)]), base_agent.provider)
        update = asyncio.run(
            agent.run({"industry_sentiments": SENTIMENTS, "analysis_date": "2026-08-11"})
        )
        self.assertIn("industry_research_capital", update)
        self.assertEqual(update["research_capital_metadata"]["data_mode"], "simulated")
        self.assertIn("模拟数据", update["research_capital_metadata"]["warning"])


if __name__ == "__main__":
    unittest.main()
