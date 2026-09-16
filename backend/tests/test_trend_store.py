from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.workflow.trend_store import TrendSnapshotStore


def industries(order: list[str], scores: dict[str, int] | None = None) -> list[dict]:
    scores = scores or {}
    return [
        {
            "industry": name,
            "combined_score": scores.get(name, 90 - index * 5),
            "market_hot_score": scores.get(name, 88 - index * 4),
            "policy_support_score": scores.get(name, 82 - index * 3),
        }
        for index, name in enumerate(order)
    ]


def sentiments(names: list[str], base: int = 75) -> list[dict]:
    return [{"industry": name, "sentiment_score": base - index * 3} for index, name in enumerate(names)]


class TrendSnapshotStoreTests(unittest.TestCase):
    def test_persists_rank_history_and_detects_warming_and_cooling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TrendSnapshotStore(Path(directory) / "trends.sqlite3")
            now = datetime.now(timezone.utc)
            runs = [
                (["半导体", "能源", "机器人", "医药"], {}),
                (["半导体", "机器人", "能源", "医药"], {}),
                (["机器人", "医药", "半导体", "能源"], {"机器人": 96, "能源": 55}),
            ]
            for index, (order, scores) in enumerate(runs):
                store.save(
                    industries(order, scores), sentiments(order), analysis_mode="rule_based",
                    captured_at=(now - timedelta(hours=2 - index)).isoformat(),
                )
            result = store.build_trends(limit=5, hours=24)
            values = {item["industry"]: item for item in result["industries"]}
            self.assertEqual(result["sample_count"], 3)
            self.assertEqual(values["机器人"]["rank_history"], [3, 2, 1])
            self.assertIn("连续3次升温", values["机器人"]["tags"])
            self.assertIn("快速降温", values["能源"]["tags"])
            self.assertGreater(values["机器人"]["persistence_hours"], 0)

    def test_first_snapshot_is_explicit_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TrendSnapshotStore(Path(directory) / "trends.sqlite3")
            names = ["机器人", "半导体", "医药"]
            store.save(industries(names), sentiments(names), analysis_mode="rule_based")
            result = store.build_trends()
            self.assertEqual(result["sample_count"], 1)
            self.assertTrue(all(item["tags"] == ["趋势基线"] for item in result["industries"]))
            self.assertTrue(all(item["score_change_24h"] == 0 for item in result["industries"]))


if __name__ == "__main__":
    unittest.main()
