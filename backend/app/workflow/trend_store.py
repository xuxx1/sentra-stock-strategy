"""行业分析快照持久化与趋势计算。仅使用 Python 标准库 SQLite。"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class TrendSnapshotStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                """CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    analysis_mode TEXT NOT NULL,
                    industry_count INTEGER NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS industry_snapshots (
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    industry TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    combined_score REAL NOT NULL,
                    market_hot_score REAL NOT NULL,
                    policy_support_score REAL NOT NULL,
                    sentiment_score REAL NOT NULL,
                    PRIMARY KEY (run_id, industry)
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_runs_captured_at ON analysis_runs(captured_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_industry_run ON industry_snapshots(industry, run_id DESC)")
            db.execute("PRAGMA optimize")

    def save(
        self,
        industries: Sequence[Mapping[str, Any]],
        sentiments: Sequence[Mapping[str, Any]],
        *,
        analysis_mode: str,
        captured_at: str | None = None,
    ) -> int:
        timestamp = captured_at or datetime.now(timezone.utc).isoformat()
        sentiment_map = {str(item.get("industry") or ""): self._number(item.get("sentiment_score")) for item in sentiments}
        rows = []
        for rank, item in enumerate(industries, start=1):
            industry = str(item.get("industry") or "").strip()
            if not industry:
                continue
            rows.append((industry, rank, self._number(item.get("combined_score")), self._number(item.get("market_hot_score")), self._number(item.get("policy_support_score")), sentiment_map.get(industry, 0.0)))
        if not rows:
            raise ValueError("没有可保存的行业趋势数据")
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT INTO analysis_runs(captured_at, analysis_mode, industry_count) VALUES (?, ?, ?)",
                (timestamp, analysis_mode, len(rows)),
            )
            run_id = int(cursor.lastrowid)
            db.executemany(
                """INSERT INTO industry_snapshots(
                    run_id, industry, rank, combined_score, market_hot_score,
                    policy_support_score, sentiment_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [(run_id, *row) for row in rows],
            )
        return run_id

    def build_trends(self, *, limit: int = 5, hours: int = 24) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as db, db:
            runs = db.execute(
                "SELECT id, captured_at, analysis_mode, industry_count FROM analysis_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            if not runs:
                return {"sample_count": 0, "window_hours": hours, "snapshots": [], "industries": []}
            run_ids = [int(row["id"]) for row in reversed(runs)]
            placeholders = ",".join("?" for _ in run_ids)
            rows = db.execute(
                f"SELECT * FROM industry_snapshots WHERE run_id IN ({placeholders}) ORDER BY run_id, rank",
                run_ids,
            ).fetchall()
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            baseline = db.execute(
                """SELECT s.* FROM industry_snapshots s
                   JOIN analysis_runs r ON r.id=s.run_id
                   WHERE r.captured_at >= ?
                   ORDER BY r.captured_at ASC, s.rank ASC""",
                (cutoff,),
            ).fetchall()

        run_times = {int(row["id"]): str(row["captured_at"]) for row in runs}
        by_industry: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            point = self._point(row, run_times[int(row["run_id"])])
            by_industry.setdefault(str(row["industry"]), []).append(point)
        baseline_map: dict[str, dict[str, Any]] = {}
        for row in baseline:
            baseline_map.setdefault(str(row["industry"]), dict(row))

        previous_names = {
            str(row["industry"])
            for row in rows
            if len(run_ids) > 1 and int(row["run_id"]) == run_ids[-2]
        }
        current_names = {
            str(row["industry"])
            for row in rows
            if int(row["run_id"]) == run_ids[-1]
        }
        industries = []
        for name in current_names:
            points = by_industry[name]
            latest = points[-1]
            first_24h = baseline_map.get(name)
            rank_history = [point["rank"] for point in points]
            score_delta = round(latest["combined_score"] - (float(first_24h["combined_score"]) if first_24h else latest["combined_score"]), 1)
            rank_delta = (int(first_24h["rank"]) - latest["rank"]) if first_24h else 0
            consecutive_warming = self._consecutive_warming(rank_history)
            new_entry = len(run_ids) > 1 and name not in previous_names
            tags: list[str] = []
            if new_entry and latest["rank"] <= 3:
                tags.append("首次爆发")
            elif new_entry:
                tags.append("新进入榜")
            if consecutive_warming >= 2:
                tags.append(f"连续{consecutive_warming}次升温")
            if len(rank_history) >= 2 and (rank_history[-1] - rank_history[-2] >= 2 or points[-1]["combined_score"] - points[-2]["combined_score"] <= -12):
                tags.append("快速降温")
            if len(points) >= 2:
                market_change = points[-1]["market_hot_score"] - points[-2]["market_hot_score"]
                policy_change = points[-1]["policy_support_score"] - points[-2]["policy_support_score"]
                sentiment_change = points[-1]["sentiment_score"] - points[-2]["sentiment_score"]
                if policy_change >= 8 and market_change <= 2:
                    tags.append("政策先行")
                if market_change >= 8 and policy_change <= 2:
                    tags.append("市场先行")
                if latest["combined_score"] >= 75 and sentiment_change <= -8:
                    tags.append("高热情绪回落")
            first_seen = points[0]["captured_at"]
            duration = max(0.0, (self._parse(points[-1]["captured_at"]) - self._parse(first_seen)).total_seconds() / 3600)
            industries.append({
                "industry": name,
                "current_rank": latest["rank"],
                "current_score": latest["combined_score"],
                "score_change_24h": score_delta,
                "rank_change_24h": rank_delta,
                "rank_history": rank_history,
                "tags": tags or (["趋势基线"] if len(points) == 1 else ["震荡观察"]),
                "persistence_hours": round(duration, 1),
                "points": points,
            })
        industries.sort(key=lambda item: item["current_rank"])
        snapshots = [
            {"id": int(row["id"]), "captured_at": str(row["captured_at"]), "analysis_mode": str(row["analysis_mode"]), "industry_count": int(row["industry_count"])}
            for row in reversed(runs)
        ]
        return {"sample_count": len(run_ids), "window_hours": hours, "snapshots": snapshots, "industries": industries}

    @staticmethod
    def _point(row: sqlite3.Row, captured_at: str) -> dict[str, Any]:
        return {
            "captured_at": captured_at,
            "rank": int(row["rank"]),
            "combined_score": float(row["combined_score"]),
            "market_hot_score": float(row["market_hot_score"]),
            "policy_support_score": float(row["policy_support_score"]),
            "sentiment_score": float(row["sentiment_score"]),
        }

    @staticmethod
    def _consecutive_warming(ranks: Sequence[int]) -> int:
        if len(ranks) < 2:
            return 0
        count = 1
        for index in range(len(ranks) - 1, 0, -1):
            if ranks[index] < ranks[index - 1]:
                count += 1
            else:
                break
        return count if count > 1 else 0

    @staticmethod
    def _parse(value: str) -> datetime:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return round(float(value or 0), 2)
        except (TypeError, ValueError, OverflowError):
            return 0.0
