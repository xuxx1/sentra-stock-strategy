from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.workflow.pipeline import PipelineService
from backend.app.workflow.rule_based import RuleBasedAnalysisEngine


TOPICS = [
    {"title": "宇树机器人热度上升", "content": "人形机器人产业链活跃", "read_count": 500000, "comment_count": 8000, "stocks": [{"name": "三花智控"}]},
    {"title": "AI 算力服务器受关注", "content": "数据中心与光通信走强", "read_count": 420000, "comment_count": 6000, "stocks": [{"name": "中际旭创"}]},
    {"title": "国产芯片板块升温", "content": "半导体和集成电路讨论增加", "read_count": 380000, "comment_count": 5000, "stocks": [{"name": "北方华创"}]},
]
ARTICLES = [
    {"title": "支持人工智能基础设施建设", "content": "政策支持算力和数据中心投资发展"},
    {"title": "机器人产业规划发布", "content": "智能制造政策支持人形机器人发展"},
    {"title": "国产替代加快", "content": "半导体芯片产业获得政策支持"},
]


class RuleBasedWorkflowTests(unittest.TestCase):
    def make_service(self) -> PipelineService:
        return PipelineService(trend_db_path=Path(self._temp_dir.name) / "test-trends.sqlite3")

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)

    def test_engine_generates_complete_strategy_without_llm(self) -> None:
        result = asyncio.run(
            RuleBasedAnalysisEngine().run(
                {"guba_topics": TOPICS, "finance_commentary": ARTICLES, "analysis_date": "2026-08-11"}
            )
        )
        self.assertGreaterEqual(len(result["combined_industries"]), 3)
        self.assertEqual(result["strategy_metadata"]["analysis_mode"], "rule_based")
        self.assertTrue(result["strategy_metadata"]["is_simulation"])
        self.assertIn("# 5日短线交易策略报告", result["trading_strategy"])
        self.assertEqual(len(result["industry_research_capital"]), len(result["combined_industries"]))

    def test_pipeline_uses_rules_when_api_key_is_absent(self) -> None:
        service = self.make_service()
        service._update(guba_topics=TOPICS, finance_commentary=ARTICLES, stage="collected")
        with patch.dict(os.environ, {}, clear=True):
            result = asyncio.run(service.analyze())
        self.assertEqual(result["stage"], "complete")
        self.assertEqual(result["analysis_metadata"]["mode"], "rule_based")
        self.assertTrue(result["analysis_metadata"]["fallback_used"])

    def test_sqlite_restores_latest_state_and_structured_history(self) -> None:
        path = Path(self._temp_dir.name) / "persistent-trends.sqlite3"
        service = PipelineService(trend_db_path=path)
        service._update(guba_topics=TOPICS, finance_commentary=ARTICLES, stage="collected")
        with patch.dict(os.environ, {}, clear=True):
            result = asyncio.run(service.analyze())
        self.assertEqual(result["persistence_status"]["counts"]["analysis_archives"], 1)
        restored = PipelineService(trend_db_path=path)
        snapshot = restored.snapshot()
        self.assertEqual(snapshot["stage"], "complete")
        self.assertEqual(len(snapshot["combined_industries"]), len(result["combined_industries"]))
        self.assertIn("# 5日短线交易策略报告", snapshot["trading_strategy"])

    def test_node_log_is_persisted(self) -> None:
        service = self.make_service()
        service._update(guba_topics=TOPICS, finance_commentary=ARTICLES, stage="collected")
        with patch.dict(os.environ, {}, clear=True):
            asyncio.run(service.run_node("industry_analysis"))
        status = service.persistence.status()
        self.assertEqual(status["counts"]["node_execution_logs"], 1)

    def test_data_trust_reports_real_and_simulated_sources(self) -> None:
        service = self.make_service()
        now = datetime.now(timezone.utc).isoformat()
        articles = [
            {
                **ARTICLES[0],
                "time": (datetime.now(timezone.utc) - timedelta(minutes=30)).astimezone().strftime("%Y/%m/%d %H:%M:%S"),
                "url": "https://finance.eastmoney.com/a/test.html",
            }
        ]
        topics = [{**TOPICS[0], "url": "https://gubatopic.eastmoney.com/test"}]
        service._update(
            guba_topics=topics,
            finance_commentary=articles,
            collection_summary={"guba_topic_count": 1, "finance_article_count": 1, "collected_at": now},
            source_stats={
                "guba": {"attempts": 2, "successes": 1, "last_failure": "历史超时"},
                "finance": {"attempts": 1, "successes": 1, "last_failure": ""},
            },
            analysis_completed_at=now,
            industry_research_capital=[{"industry": "算力"}],
            trading_strategy="report",
        )
        trust = service.public_result()["data_trust"]
        sources = {item["key"]: item for item in trust["sources"]}
        self.assertEqual(len(sources), 5)
        self.assertEqual(sources["guba"]["mode"], "real")
        self.assertEqual(sources["guba"]["success_rate"], 50.0)
        self.assertEqual(sources["guba"]["last_failure"], "历史超时")
        self.assertEqual(sources["finance"]["freshness"], "fresh")
        self.assertIsNotNone(sources["finance"]["publication_lag_minutes"])
        self.assertEqual(sources["market"]["mode"], "simulated")
        self.assertIsNone(sources["market"]["success_rate"])

    def test_nodes_record_execution_metrics_and_can_rerun_individually(self) -> None:
        service = self.make_service()
        service._update(guba_topics=TOPICS, finance_commentary=ARTICLES, stage="collected")
        with patch.dict(os.environ, {}, clear=True):
            industry = asyncio.run(service.run_node("industry_analysis"))
            fusion = asyncio.run(service.run_node("industry_fusion"))
        nodes = {item["id"]: item for item in fusion["workflow_nodes"]}
        self.assertEqual(nodes["industry_analysis"]["status"], "success")
        self.assertEqual(nodes["industry_analysis"]["mode"], "rule_based")
        self.assertEqual(nodes["industry_analysis"]["input_count"], 6)
        self.assertGreaterEqual(nodes["industry_analysis"]["output_count"], 3)
        self.assertGreaterEqual(nodes["industry_analysis"]["duration_ms"], 0)
        self.assertEqual(nodes["industry_analysis"]["run_count"], 1)
        self.assertIn("guba_industries", nodes["industry_analysis"]["output"])
        self.assertEqual(nodes["industry_fusion"]["status"], "success")
        self.assertTrue(industry["workflow_nodes"])

    def test_node_rerun_rejects_missing_prerequisites(self) -> None:
        service = self.make_service()
        with self.assertRaisesRegex(Exception, "缺少前置数据"):
            asyncio.run(service.run_node("strategy_report"))


if __name__ == "__main__":
    unittest.main()
