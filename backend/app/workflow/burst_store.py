"""周期采集快照与舆情爆发增长率计算。"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.app.workflow.rule_based import RuleBasedAnalysisEngine


class SentimentBurstStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS burst_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, captured_at TEXT NOT NULL,
                topic_count INTEGER NOT NULL, article_count INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS burst_metrics(
                run_id INTEGER NOT NULL REFERENCES burst_runs(id) ON DELETE CASCADE,
                entity_type TEXT NOT NULL, name TEXT NOT NULL, industry TEXT NOT NULL,
                topic_count INTEGER NOT NULL, read_count REAL NOT NULL,
                comment_count REAL NOT NULL, news_count INTEGER NOT NULL,
                guba_hits INTEGER NOT NULL, news_hits INTEGER NOT NULL,
                PRIMARY KEY(run_id, entity_type, name)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_burst_runs_time ON burst_runs(captured_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_burst_metric_name ON burst_metrics(entity_type,name,run_id)")

    def save(self, topics: Sequence[Mapping[str, Any]], articles: Sequence[Mapping[str, Any]], *, captured_at: str) -> int:
        metrics: dict[tuple[str, str], dict[str, Any]] = {}
        for industry, keywords in RuleBasedAnalysisEngine.TAXONOMY:
            metrics[("industry", industry)] = self._aggregate(industry, keywords, topics, articles)
            for keyword in keywords:
                item = self._aggregate(industry, (keyword,), topics, articles)
                if item["guba_hits"] or item["news_hits"]:
                    metrics[("keyword", keyword)] = item
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("INSERT INTO burst_runs(captured_at,topic_count,article_count) VALUES(?,?,?)", (captured_at, len(topics), len(articles)))
            run_id = int(cursor.lastrowid)
            db.executemany("""INSERT INTO burst_metrics(run_id,entity_type,name,industry,topic_count,read_count,comment_count,news_count,guba_hits,news_hits)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", [(run_id, kind, name, item["industry"], item["topic_count"], item["read_count"], item["comment_count"], item["news_count"], item["guba_hits"], item["news_hits"]) for (kind, name), item in metrics.items()])
        return run_id

    def radar(self, *, hours: int = 1, limit: int = 8) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as db:
            runs = db.execute("SELECT * FROM burst_runs ORDER BY id DESC LIMIT 2").fetchall()
            total = int(db.execute("SELECT COUNT(*) FROM burst_runs").fetchone()[0])
            if not runs:
                return self._empty(0, hours)
            latest = runs[0]
            previous = runs[1] if len(runs) > 1 else None
            latest_rows = db.execute("SELECT * FROM burst_metrics WHERE run_id=?", (int(latest["id"]),)).fetchall()
            previous_rows = db.execute("SELECT * FROM burst_metrics WHERE run_id=?", (int(previous["id"]),)).fetchall() if previous else []
            first_seen = {str(row["name"]): str(row["first_seen"]) for row in db.execute("""SELECT m.name, MIN(r.captured_at) first_seen FROM burst_metrics m JOIN burst_runs r ON r.id=m.run_id GROUP BY m.entity_type,m.name""").fetchall()}
        ready = bool(previous) and self._parse(str(previous["captured_at"])) >= self._parse(str(latest["captured_at"])) - timedelta(hours=hours)
        baseline = {(str(row["entity_type"]), str(row["name"])): row for row in previous_rows} if ready else {}
        items = []
        for row in latest_rows:
            old = baseline.get((str(row["entity_type"]), str(row["name"])))
            read_growth = self._growth(float(row["read_count"]), float(old["read_count"])) if old else None
            comment_growth = self._growth(float(row["comment_count"]), float(old["comment_count"])) if old else None
            news_growth = self._growth(float(row["news_count"]), float(old["news_count"])) if old else None
            discussion_delta = max(0, round(float(row["comment_count"]) - (float(old["comment_count"]) if old else float(row["comment_count"])))) if ready else None
            source = "股吧 + 财经新闻" if row["guba_hits"] and row["news_hits"] else "股吧" if row["guba_hits"] else "财经新闻"
            intensity = max(value for value in (read_growth, comment_growth, news_growth, 0) if value is not None)
            items.append({"type": str(row["entity_type"]), "name": str(row["name"]), "industry": str(row["industry"]), "discussion_delta_1h": discussion_delta, "read_growth_rate": read_growth, "comment_growth_rate": comment_growth, "news_growth_rate": news_growth, "source": source, "first_seen_at": first_seen.get(str(row["name"]), str(latest["captured_at"])), "burst_score": round(intensity, 1), "is_new": ready and old is None})
        items.sort(key=lambda item: (-int(item["is_new"]), -item["burst_score"], item["name"]))
        return {"ready": ready, "sample_count": total, "window_hours": hours, "latest_at": str(latest["captured_at"]), "baseline_at": str(previous["captured_at"]) if ready and previous else None, "keywords": [item for item in items if item["type"] == "keyword"][:limit], "industries": [item for item in items if item["type"] == "industry"][:limit], "message": "已按最近两次周期采集计算1小时增长率" if ready else "至少需要两次、且间隔不超过1小时的真实采集才能计算增长率"}

    def _aggregate(self, industry: str, keywords: Sequence[str], topics: Sequence[Mapping[str, Any]], articles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        matched_topics = [item for item in topics if any(word.lower() in f"{item.get('title','')} {item.get('content','')}".lower() for word in keywords)]
        matched_articles = [item for item in articles if any(word.lower() in f"{item.get('title','')} {item.get('content','')}".lower() for word in keywords)]
        return {"industry": industry, "topic_count": len(matched_topics), "read_count": sum(self._number(item.get("read_count")) for item in matched_topics), "comment_count": sum(self._number(item.get("comment_count")) for item in matched_topics), "news_count": len(matched_articles), "guba_hits": len(matched_topics), "news_hits": len(matched_articles)}

    @staticmethod
    def _growth(current: float, previous: float) -> float | None:
        if previous <= 0: return None if current <= 0 else 100.0
        return round((current - previous) / previous * 100, 1)

    @staticmethod
    def _parse(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")); return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0)
        except (TypeError, ValueError, OverflowError): return 0.0

    @staticmethod
    def _empty(samples: int, hours: int) -> dict[str, Any]:
        return {"ready": False, "sample_count": samples, "window_hours": hours, "latest_at": None, "baseline_at": None, "keywords": [], "industries": [], "message": "完成首次真实采集后建立爆发监测基线"}
