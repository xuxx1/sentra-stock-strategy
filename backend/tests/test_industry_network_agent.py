from __future__ import annotations

import asyncio
import json
import unittest

from backend.app.agents import IndustryNetworkAgent


INDUSTRIES = [
    {
        "industry": "算力",
        "combined_score": 94,
        "market_hot_score": 91,
        "policy_support_score": 90,
        "combined_logic": "算力需求与数字基础设施政策形成共振。",
        "hot_topics": ["算力基础设施关注度升温"],
        "policy_signals": ["数字基础设施支持政策（预期）"],
    },
    {
        "industry": "半导体",
        "combined_score": 86,
        "market_hot_score": 84,
        "policy_support_score": 82,
        "combined_logic": "芯片供给与算力需求相关。",
        "hot_topics": ["半导体设备国产替代"],
        "policy_signals": [],
    },
    {
        "industry": "数据中心",
        "combined_score": 80,
        "market_hot_score": 77,
        "policy_support_score": 76,
        "combined_logic": "数据中心是算力基础设施的主要载体。",
        "hot_topics": [],
        "policy_signals": ["数据中心建设支持（预期）"],
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


def response() -> str:
    return json.dumps(
        {
            "core_industries": ["算力", "虚构行业"],
            "industry_relations": {
                "算力": {
                    "upstream": ["半导体", "算力", "虚构行业"],
                    "downstream": ["数据中心"],
                    "related": ["半导体"],
                },
                "半导体": {"upstream": [], "downstream": [], "related": []},
            },
            "analysis": "算力处于网络核心，半导体提供上游支撑，数据中心承接下游需求。",
        },
        ensure_ascii=False,
    )


class IndustryNetworkAgentTests(unittest.TestCase):
    def test_filters_unknown_and_self_nodes(self) -> None:
        agent = IndustryNetworkAgent(FakeLLM([response()]))
        result = asyncio.run(agent.analyze(INDUSTRIES))
        self.assertEqual(result["core_industries"], ["算力"])
        self.assertEqual(result["industry_relations"]["算力"]["upstream"], ["半导体"])
        self.assertNotIn("虚构行业", result["industry_relations"])
        self.assertNotIn("算力", result["industry_relations"]["算力"]["upstream"])

    def test_completes_reverse_supply_chain_edges(self) -> None:
        agent = IndustryNetworkAgent(FakeLLM([response()]))
        result = asyncio.run(agent.analyze(INDUSTRIES))
        self.assertIn("算力", result["industry_relations"]["半导体"]["downstream"])
        self.assertIn("算力", result["industry_relations"]["数据中心"]["upstream"])
        self.assertNotIn("半导体", result["industry_relations"]["算力"]["related"])

    def test_empty_core_falls_back_to_high_score_industries(self) -> None:
        raw = json.loads(response())
        raw["core_industries"] = ["虚构行业"]
        agent = IndustryNetworkAgent(FakeLLM([json.dumps(raw, ensure_ascii=False)]))
        result = asyncio.run(agent.analyze(INDUSTRIES))
        self.assertEqual(result["core_industries"][0], "算力")
        self.assertEqual(len(result["core_industries"]), 2)

    def test_invalid_response_is_retried(self) -> None:
        llm = FakeLLM(["not-json", response()])
        agent = IndustryNetworkAgent(llm)
        result = asyncio.run(agent.analyze(INDUSTRIES))
        self.assertEqual(result["core_industries"], ["算力"])
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("图结构校验", llm.calls[1])

    def test_workflow_state_contract(self) -> None:
        agent = IndustryNetworkAgent(FakeLLM([response()]))
        update = asyncio.run(agent.run({"combined_industries": INDUSTRIES}))
        self.assertIn("industry_network", update)
        self.assertIn("industry_relations", update["industry_network"])


if __name__ == "__main__":
    unittest.main()
