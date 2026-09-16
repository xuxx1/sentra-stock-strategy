from datetime import datetime
import asyncio
import unittest
from zoneinfo import ZoneInfo

from backend.app.workflow.pipeline import PipelineService
from backend.app.workflow.scheduler import CollectionScheduler


class CollectionSchedulerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "trends.sqlite3"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_scheduler_has_protected_market_day_plan(self):
        service = PipelineService(trend_db_path=self.db_path)
        scheduler = CollectionScheduler(service)
        service.attach_scheduler(scheduler)
        now = datetime(2026, 8, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        status = scheduler.status(now)

        self.assertTrue(status["enabled"])
        self.assertEqual(status["next_run"]["job_id"], "important_news_0820")
        self.assertEqual(len(status["jobs"]), 5)
        self.assertTrue(status["limits"]["single_flight"])
        self.assertEqual(status["limits"]["daily_full_limit"], 12)

    def test_scheduler_skips_weekend_and_persists_switch(self):
        service = PipelineService(trend_db_path=self.db_path)
        scheduler = CollectionScheduler(service)
        saturday = datetime(2026, 8, 15, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertFalse(scheduler.is_trading_day(saturday))

        asyncio.run(scheduler.disable())
        restored = CollectionScheduler(service)
        self.assertFalse(restored.status(saturday)["enabled"])
        self.assertIsNone(restored.status(saturday)["next_run"])
