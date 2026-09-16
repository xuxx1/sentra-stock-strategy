"""Beijing-time collection scheduler with source-friendly rate limits."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, time, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo("Asia/Shanghai")


class CollectionScheduler:
    DEFAULTS: dict[str, Any] = {
        "enabled": True,
        "timezone": "Asia/Shanghai",
        "pre_market": "08:45",
        "midday": "11:35",
        "post_close": "15:15",
        "intraday_times": ["09:30", "10:00", "10:30", "11:00", "13:00", "13:30", "14:00", "14:30"],
        "news_check_minutes": 20,
        "news_window": ["07:40", "18:20"],
        "min_full_interval_minutes": 25,
        "min_news_interval_minutes": 15,
        "daily_full_limit": 12,
        "daily_news_limit": 32,
        "max_backoff_minutes": 60,
        "calendar_mode": "weekday_only",
    }

    def __init__(self, service: Any) -> None:
        self.service = service
        self.store = service.persistence
        self.config = self.store.load_scheduler_config(self.DEFAULTS)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failure_count = 0
        self._backoff_until: datetime | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="sentra-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    async def enable(self) -> dict[str, Any]:
        self.config["enabled"] = True
        self.store.save_scheduler_config(self.config)
        return self.service.public_result()

    async def disable(self) -> dict[str, Any]:
        self.config["enabled"] = False
        self.store.save_scheduler_config(self.config)
        return self.service.public_result()

    @staticmethod
    def is_trading_day(moment: datetime) -> bool:
        return moment.weekday() < 5

    def status(self, now: datetime | None = None) -> dict[str, Any]:
        now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
        runs = self.store.recent_scheduler_runs(100)
        today = now.date().isoformat()
        today_runs = [item for item in runs if str(item.get("started_at", ""))[:10] == today]
        full_count = sum(item.get("trigger_type") == "full" and item.get("status") == "success" for item in today_runs)
        news_count = sum(item.get("trigger_type") == "incremental_news" and item.get("status") == "success" for item in today_runs)
        return {
            "enabled": bool(self.config.get("enabled")),
            "timezone": "北京时间",
            "calendar_mode": self.config.get("calendar_mode"),
            "calendar_note": "当前按周一至周五判断；法定节假日与调休交易日历尚未接入。",
            "running": bool(self._thread and self._thread.is_alive()),
            "next_run": self._next_run(now),
            "backoff_until": self._backoff_until.isoformat() if self._backoff_until else "",
            "today": {"full_runs": full_count, "news_checks": news_count,
                      "skipped": sum(item.get("status") == "skipped" for item in today_runs)},
            "limits": {
                "full_min_interval_minutes": self.config["min_full_interval_minutes"],
                "news_min_interval_minutes": self.config["min_news_interval_minutes"],
                "daily_full_limit": self.config["daily_full_limit"],
                "daily_news_limit": self.config["daily_news_limit"],
                "max_backoff_minutes": self.config["max_backoff_minutes"],
                "single_flight": True,
            },
            "jobs": self._job_descriptions(),
            "recent_runs": runs[:8],
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick(datetime.now(BEIJING))
            except Exception as exc:  # scheduler must never stop the API process
                print(f"[scheduler] tick failed: {exc}")
            self._stop.wait(30)

    def _tick(self, now: datetime) -> None:
        if not self.config.get("enabled") or not self.is_trading_day(now):
            return
        if self._backoff_until and now < self._backoff_until:
            return
        for job in self._due_jobs(now):
            planned_at = job["planned_at"].isoformat()
            if self.store.has_scheduler_run(job["id"], planned_at):
                continue
            self._execute(job, planned_at, now)
            break

    def _execute(self, job: Mapping[str, Any], planned_at: str, now: datetime) -> None:
        reason = self._limit_reason(str(job["trigger_type"]), now)
        if reason:
            self._record(job, planned_at, now, "skipped", {"reason": reason})
            return
        if not self.service.run_lock.acquire(blocking=False):
            self._record(job, planned_at, now, "skipped", {"reason": "已有工作流任务运行，互斥保护已跳过"})
            return
        started = datetime.now(BEIJING)
        try:
            if job["trigger_type"] == "incremental_news":
                detail = asyncio.run(self.service.incremental_news_check())
            else:
                asyncio.run(self.service.run_full())
                detail = {"action": "full_collection_and_analysis"}
            self._failure_count = 0
            self._backoff_until = None
            self._record(job, planned_at, started, "success", detail)
        except Exception as exc:
            self._failure_count += 1
            minutes = min(int(self.config["max_backoff_minutes"]), 5 * (2 ** (self._failure_count - 1)))
            self._backoff_until = datetime.now(BEIJING) + timedelta(minutes=minutes)
            self._record(job, planned_at, started, "failed", {"backoff_minutes": minutes}, str(exc))
        finally:
            self.service.run_lock.release()

    def _record(self, job: Mapping[str, Any], planned_at: str, started: datetime,
                status: str, detail: Mapping[str, Any], error: str = "") -> None:
        self.store.save_scheduler_run(
            job_id=str(job["id"]), trigger_type=str(job["trigger_type"]), planned_at=planned_at,
            started_at=started.isoformat(), ended_at=datetime.now(BEIJING).isoformat(),
            status=status, detail=detail, error=error,
        )

    def _limit_reason(self, trigger_type: str, now: datetime) -> str:
        runs = self.store.recent_scheduler_runs(100)
        today = now.date().isoformat()
        successful = [item for item in runs if item.get("status") == "success"]
        same_type = [item for item in successful if item.get("trigger_type") == trigger_type]
        daily = [item for item in same_type if str(item.get("started_at", ""))[:10] == today]
        limit = int(self.config["daily_news_limit"] if trigger_type == "incremental_news" else self.config["daily_full_limit"])
        if len(daily) >= limit:
            return f"已达到每日上限 {limit} 次"
        if same_type:
            try:
                last = datetime.fromisoformat(str(same_type[0]["ended_at"])).astimezone(BEIJING)
                minimum = int(self.config["min_news_interval_minutes"] if trigger_type == "incremental_news" else self.config["min_full_interval_minutes"])
                if now - last < timedelta(minutes=minimum):
                    return f"距上次同类访问不足 {minimum} 分钟"
            except (ValueError, TypeError):
                pass
        return ""

    def _due_jobs(self, now: datetime) -> list[dict[str, Any]]:
        jobs = self._planned_jobs(now)
        return [job for job in jobs if timedelta(0) <= now - job["planned_at"] < timedelta(minutes=3)]

    def _planned_jobs(self, now: datetime) -> list[dict[str, Any]]:
        day = now.date()
        jobs = [self._job("pre_market", "早盘前采集", "full", day, self.config["pre_market"])]
        jobs.extend(self._job(f"intraday_{value.replace(':', '')}", "盘中30分钟采集", "full", day, value)
                    for value in self.config["intraday_times"])
        jobs.append(self._job("midday", "午盘采集", "full", day, self.config["midday"]))
        jobs.append(self._job("post_close", "收盘后采集", "full", day, self.config["post_close"]))
        start = self._at(day, self.config["news_window"][0])
        end = self._at(day, self.config["news_window"][1])
        cursor = start
        while cursor <= end:
            jobs.append({"id": f"important_news_{cursor:%H%M}", "name": "重要新闻增量检查",
                         "trigger_type": "incremental_news", "planned_at": cursor})
            cursor += timedelta(minutes=int(self.config["news_check_minutes"]))
        return sorted(jobs, key=lambda item: item["planned_at"])

    def _next_run(self, now: datetime) -> dict[str, str] | None:
        if not self.config.get("enabled"):
            return None
        for offset in range(8):
            candidate = now + timedelta(days=offset)
            if not self.is_trading_day(candidate):
                continue
            for job in self._planned_jobs(candidate):
                if job["planned_at"] > now and not self.store.has_scheduler_run(job["id"], job["planned_at"].isoformat()):
                    return {"job_id": job["id"], "name": job["name"], "planned_at": job["planned_at"].isoformat()}
        return None

    def _job_descriptions(self) -> list[dict[str, Any]]:
        return [
            {"id": "pre_market", "name": "早盘前", "schedule": f"交易日 {self.config['pre_market']}", "action": "全量采集 + 分析"},
            {"id": "intraday", "name": "盘中", "schedule": "上午/下午每30分钟", "action": "全量采集 + 分析"},
            {"id": "midday", "name": "午盘", "schedule": f"交易日 {self.config['midday']}", "action": "全量采集 + 分析"},
            {"id": "post_close", "name": "收盘后", "schedule": f"交易日 {self.config['post_close']}", "action": "全量采集 + 分析"},
            {"id": "important_news", "name": "重要新闻", "schedule": f"07:40–18:20 / 每{self.config['news_check_minutes']}分钟", "action": "只抓财经增量；命中重要词才分析"},
        ]

    @classmethod
    def _job(cls, job_id: str, name: str, trigger_type: str, day: Any, value: str) -> dict[str, Any]:
        return {"id": job_id, "name": name, "trigger_type": trigger_type, "planned_at": cls._at(day, value)}

    @staticmethod
    def _at(day: Any, value: str) -> datetime:
        hour, minute = (int(part) for part in value.split(":"))
        return datetime.combine(day, time(hour, minute), tzinfo=BEIJING)
