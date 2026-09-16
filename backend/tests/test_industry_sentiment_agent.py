from __future__ import annotations

import asyncio
import json
import unittest

from backend.app.agents import IndustrySentimentAgent


INDUSTRIES = [
    {
        "industry": "算力",
        "combined_score": 94,
        "market_hot_score": 91,
        "policy_support_score": 90,
        "combined_logic": "市场关注和政策预期形成共振。",
        "hot_topics": ["算力基础设施关注度升温"],
        "policy_signals": ["数字基础设施支持政策（预期）"],
    },
    {
        "industry": "半导体",
        "combined_score": 58,
        "market_hot_score": 70,
        "policy_support_score": 35,
        "combined_logic": "市场关注较高，但政策证据相对有限。",
        "hot_topics": ["半导体设备国产替代"],
        "policy_signals": [],
    },
]

NETWORK = {
    "core_industries": ["算力"],
    "industry_relations": {
        "算力": {"upstream": ["半导体"], "downstream": [], "related": []},
        "半导体": {"upstream": [], "downstream": ["算力"], "related": []},
    },
    "analysis": "算力是网络核心，半导体处于上游。",
}


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


def response(*, computing_score: int = 85, include_semiconductor: bool = True) -> str:
    values = [
        {
            "industry": "算力",
            "sentiment": "positive",
            "sentiment_score": computing_score,
            "sentiment_drivers": ["市场热度与政策预期共振", "处于关联网络核心"],
            "risk_factors": ["政策预期未兑现", "上游供给传导不及预期"],
        }
    ]
    if include_semiconductor:
        values.append(
            {
                "industry": "半导体",
                "sentiment": "neutral",
                "sentiment_score": 56,
                "sentiment_drivers": ["市场关注较高但政策支持有限"],
                "risk_factors": ["下游需求传导存在不确定性"],
            }
        )
    return json.dumps(values, ensure_ascii=False)


class IndustrySentimentAgentTests(unittest.TestCase):
    def test_returns_every_industry_in_score_order(self) -> None:
        agent = IndustrySentimentAgent(FakeLLM([response()]))
        result = asyncio.run(agent.analyze(INDUSTRIES, NETWORK))
        self.assertEqual([item["industry"] for item in result], ["算力", "半导体"])
        self.assertEqual(result[0]["sentiment"], "positive")
        self.assertEqual(result[1]["sentiment"], "neutral")

    def test_inconsistent_label_and_score_is_retried(self) -> None:
        llm = FakeLLM([response(computing_score=30), response()])
        agent = IndustrySentimentAgent(llm)
        result = asyncio.run(agent.analyze(INDUSTRIES, NETWORK))
        self.assertEqual(result[0]["sentiment_score"], 85)
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("分数一致性校验", llm.calls[1])

    def test_missing_industry_is_retried(self) -> None:
        llm = FakeLLM([response(include_semiconductor=False), response()])
        agent = IndustrySentimentAgent(llm)
        result = asyncio.run(agent.analyze(INDUSTRIES, NETWORK))
        self.assertEqual(len(result), 2)
        self.assertEqual(len(llm.calls), 2)

    def test_unknown_industry_is_ignored(self) -> None:
        values = json.loads(response())
        values.append(
            {
                "industry": "虚构行业",
                "sentiment": "positive",
                "sentiment_score": 99,
                "sentiment_drivers": ["虚构信息"],
                "risk_factors": [],
            }
        )
        agent = IndustrySentimentAgent(FakeLLM([json.dumps(values, ensure_ascii=False)]))
        result = asyncio.run(agent.analyze(INDUSTRIES, NETWORK))
        self.assertEqual(len(result), 2)

    def test_workflow_state_contract(self) -> None:
        agent = IndustrySentimentAgent(FakeLLM([response()]))
        update = asyncio.run(
            agent.run({"combined_industries": INDUSTRIES, "industry_network": NETWORK})
        )
        self.assertIn("industry_sentiments", update)


if __name__ == "__main__":
    unittest.main()
