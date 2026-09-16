from __future__ import annotations

import asyncio
import json
import unittest

from backend.app.agents import FinanceIndustryAnalysisAgent


ARTICLES = [
    {
        "title": "降准释放长期流动性，支持实体经济",
        "time": "2026-08-10 09:30:00",
        "content": "文章认为降准已经落地，有助于释放长期流动性，并降低银行负债成本。",
        "url": "https://finance.eastmoney.com/a/1.html",
    },
    {
        "title": "促消费政策有望继续加力",
        "time": "2026-08-09 10:00:00",
        "content": "作者建议扩大消费品以旧换新支持范围，但该措施仍属于政策建议。",
        "url": "https://finance.eastmoney.com/a/2.html",
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


def valid_response() -> str:
    return json.dumps(
        [
            {
                "industry": "银行",
                "logic": "降准释放流动性并降低负债成本，但实际受益程度取决于信贷需求。",
                "macro_factors": ["流动性改善", "不存在的海外衰退"],
                "policy_signals": ["降准（已落地）", "光伏补贴（已落地）"],
            },
            {
                "industry": "消费",
                "logic": "以旧换新若扩大范围，可能改善相关消费需求，目前仍需等待政策确认。",
                "macro_factors": ["消费需求"],
                "policy_signals": ["扩大以旧换新支持范围（作者建议）"],
            },
        ],
        ensure_ascii=False,
    )


class FinanceIndustryAnalysisAgentTests(unittest.TestCase):
    def test_prepares_and_deduplicates_articles(self) -> None:
        agent = FinanceIndustryAnalysisAgent(FakeLLM([]), max_content_chars=500)
        prepared = agent.prepare_articles(ARTICLES + [ARTICLES[0]])
        self.assertEqual(len(prepared), 2)
        self.assertEqual(prepared[0]["title"], ARTICLES[0]["title"])
        self.assertLessEqual(len(prepared[0]["content"]), 500)

    def test_filters_ungrounded_macro_and_policy_claims(self) -> None:
        agent = FinanceIndustryAnalysisAgent(FakeLLM([valid_response()]))
        result = asyncio.run(agent.analyze(ARTICLES))

        self.assertEqual(result[0]["industry"], "银行")
        self.assertEqual(result[0]["macro_factors"], ["流动性改善"])
        self.assertEqual(result[0]["policy_signals"], ["降准（已落地）"])
        self.assertEqual(result[1]["policy_signals"], ["扩大以旧换新支持范围（作者建议）"])

    def test_invalid_json_is_retried(self) -> None:
        llm = FakeLLM(["invalid", valid_response()])
        agent = FinanceIndustryAnalysisAgent(llm, max_attempts=2)
        result = asyncio.run(agent.analyze(ARTICLES))
        self.assertEqual(len(result), 2)
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("原文相关性校验", llm.calls[1]["user_prompt"])

    def test_workflow_state_contract(self) -> None:
        agent = FinanceIndustryAnalysisAgent(FakeLLM([valid_response()]))
        update = asyncio.run(agent.run({"finance_commentary": ARTICLES}))
        self.assertIn("commentary_industries", update)
        self.assertEqual(update["commentary_industries"][0]["industry"], "银行")


if __name__ == "__main__":
    unittest.main()
