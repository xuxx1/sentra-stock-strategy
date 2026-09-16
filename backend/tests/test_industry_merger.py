from __future__ import annotations

import asyncio
import unittest

from backend.app.fusion import IndustryFusionNode


MARKET = [
    {
        "industry": "AI 算力板块",
        "logic": "数据中心和服务器话题热度上升。",
        "hot_topics": ["算力基础设施关注度升温", "液冷产业链讨论活跃"],
        "related_stocks": ["中科曙光"],
    },
    {
        "industry": "机器人概念",
        "logic": "人形机器人话题关注度较高。",
        "hot_topics": ["人形机器人产业化提速"],
        "related_stocks": ["三花智控"],
    },
]

POLICY = [
    {
        "industry": "算力基础设施",
        "logic": "数字基础设施政策可能改善行业需求预期。",
        "macro_factors": ["数字经济投资"],
        "policy_signals": ["算力基础设施支持政策（政策预期）"],
    },
    {
        "industry": "消费",
        "logic": "以旧换新政策可能拉动消费需求。",
        "macro_factors": ["消费需求"],
        "policy_signals": ["扩大以旧换新范围（作者建议）"],
    },
]


class IndustryFusionNodeTests(unittest.TestCase):
    def test_aliases_merge_same_industry(self) -> None:
        result = IndustryFusionNode().merge(MARKET, POLICY)
        names = [item["industry"] for item in result]
        self.assertEqual(names.count("算力"), 1)
        computing = next(item for item in result if item["industry"] == "算力")
        self.assertGreater(computing["market_hot_score"], 0)
        self.assertGreater(computing["policy_support_score"], 0)
        self.assertIn("市场侧", computing["combined_logic"])
        self.assertIn("政策侧", computing["combined_logic"])

    def test_dual_source_resonance_ranks_above_single_source(self) -> None:
        result = IndustryFusionNode().merge(MARKET, POLICY)
        self.assertEqual(result[0]["industry"], "算力")
        self.assertGreater(result[0]["combined_score"], result[1]["combined_score"])
        self.assertTrue(0 <= result[0]["combined_score"] <= 100)

    def test_evidence_is_deduplicated(self) -> None:
        duplicated_market = MARKET + [MARKET[0]]
        result = IndustryFusionNode().merge(duplicated_market, POLICY)
        computing = next(item for item in result if item["industry"] == "算力")
        self.assertEqual(
            computing["hot_topics"],
            ["算力基础设施关注度升温", "液冷产业链讨论活跃"],
        )

    def test_workflow_state_contract(self) -> None:
        node = IndustryFusionNode()
        update = asyncio.run(
            node.run({"guba_industries": MARKET, "commentary_industries": POLICY})
        )
        self.assertIn("combined_industries", update)
        self.assertEqual(update["combined_industries"][0]["industry"], "算力")

    def test_weights_must_sum_to_one(self) -> None:
        with self.assertRaises(ValueError):
            IndustryFusionNode(market_weight=0.8, policy_weight=0.5)


if __name__ == "__main__":
    unittest.main()
