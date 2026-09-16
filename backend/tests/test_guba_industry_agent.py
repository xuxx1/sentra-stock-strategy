from __future__ import annotations

import asyncio
import json
import unittest

from backend.app.agents import GubaIndustryAnalysisAgent


TOPICS = [
    {
        "title": "算力基础设施关注度升温",
        "content": "市场讨论数据中心、服务器和液冷产业链。",
        "read_count": 120_000,
        "comment_count": 3_200,
        "favorite_count": 280,
        "rank": 2,
        "tags": ["算力概念"],
        "stocks": [
            {"name": "中科曙光", "code": "603019"},
            {"name": "浪潮信息", "code": "000977"},
        ],
    },
    {
        "title": "半导体设备国产替代持续发酵",
        "content": "设备和材料环节获得讨论。",
        "read_count": 80_000,
        "comment_count": 1_800,
        "favorite_count": 190,
        "rank": 1,
        "tags": ["半导体"],
        "stocks": [{"name": "北方华创", "code": "002371"}],
    },
]


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> str:
        self.calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt, "temperature": temperature}
        )
        return self.responses.pop(0)


class GubaIndustryAnalysisAgentTests(unittest.TestCase):
    def test_prepares_topics_by_weighted_heat(self) -> None:
        agent = GubaIndustryAnalysisAgent(FakeLLM([]))
        prepared = agent.prepare_topics(TOPICS)
        self.assertEqual(prepared[0]["title"], "算力基础设施关注度升温")
        self.assertEqual(prepared[0]["heat_score"], 100.0)
        self.assertEqual(prepared[0]["heat_rank"], 1)
        self.assertNotIn("raw_heat", prepared[0])

    def test_grounding_removes_hallucinated_topics_and_stocks(self) -> None:
        response = json.dumps(
            [
                {
                    "industry": "AI 算力",
                    "logic": "高热度话题与数据中心需求形成共振，但仍需资金数据验证。",
                    "hot_topics": ["算力基础设施关注度升温", "不存在的话题"],
                    "related_stocks": ["中科曙光", "虚构股票"],
                }
            ],
            ensure_ascii=False,
        )
        agent = GubaIndustryAnalysisAgent(FakeLLM([response]))

        result = asyncio.run(agent.analyze(TOPICS))

        self.assertEqual(result[0]["hot_topics"], ["算力基础设施关注度升温"])
        self.assertEqual(result[0]["related_stocks"], ["中科曙光"])

    def test_invalid_response_is_retried(self) -> None:
        valid = json.dumps(
            [
                {
                    "industry": "半导体设备",
                    "logic": "国产替代讨论活跃，设备需求具备产业驱动。",
                    "hot_topics": ["半导体设备国产替代持续发酵"],
                    "related_stocks": ["北方华创"],
                }
            ],
            ensure_ascii=False,
        )
        llm = FakeLLM(["not-json", valid])
        agent = GubaIndustryAnalysisAgent(llm, max_attempts=2)

        result = asyncio.run(agent.analyze(TOPICS))

        self.assertEqual(result[0]["industry"], "半导体设备")
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("上一次响应未通过结构校验", llm.calls[1]["user_prompt"])

    def test_workflow_state_contract(self) -> None:
        response = json.dumps(
            [
                {
                    "industry": "AI 算力",
                    "logic": "话题热度较高。",
                    "hot_topics": ["算力基础设施关注度升温"],
                    "related_stocks": ["浪潮信息"],
                }
            ],
            ensure_ascii=False,
        )
        agent = GubaIndustryAnalysisAgent(FakeLLM([response]))
        update = asyncio.run(agent.run({"guba_topics": TOPICS}))
        self.assertIn("guba_industries", update)
        self.assertEqual(update["guba_industries"][0]["industry"], "AI 算力")


if __name__ == "__main__":
    unittest.main()
