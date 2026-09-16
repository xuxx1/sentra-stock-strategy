"""工作流主数据持久化：SQLite 初版，可平滑迁移到 PostgreSQL。"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class WorkflowPersistenceStore:
    """保存最新可恢复状态，同时保留结构化历史记录。"""

    SCHEMA_VERSION = 2

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        statements = [
            """CREATE TABLE IF NOT EXISTS schema_meta(
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS service_state(
                id INTEGER PRIMARY KEY CHECK(id=1), updated_at TEXT NOT NULL,
                stage TEXT NOT NULL, state_json TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS collection_batches(
                id INTEGER PRIMARY KEY AUTOINCREMENT, captured_at TEXT NOT NULL,
                guba_count INTEGER NOT NULL, article_count INTEGER NOT NULL,
                status TEXT NOT NULL, source_summary_json TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS raw_topics(
                id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES collection_batches(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
                read_count REAL NOT NULL, comment_count REAL NOT NULL, payload_json TEXT NOT NULL,
                UNIQUE(batch_id, ordinal)
            )""",
            """CREATE TABLE IF NOT EXISTS raw_articles(
                id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES collection_batches(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
                published_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                UNIQUE(batch_id, ordinal)
            )""",
            """CREATE TABLE IF NOT EXISTS analysis_archives(
                id INTEGER PRIMARY KEY AUTOINCREMENT, collection_batch_id INTEGER REFERENCES collection_batches(id),
                completed_at TEXT NOT NULL, analysis_mode TEXT NOT NULL, result_json TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS industry_analysis_results(
                id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER NOT NULL REFERENCES analysis_archives(id) ON DELETE CASCADE,
                result_type TEXT NOT NULL, industry TEXT NOT NULL, payload_json TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS sentiment_results(
                id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER NOT NULL REFERENCES analysis_archives(id) ON DELETE CASCADE,
                industry TEXT NOT NULL, sentiment TEXT NOT NULL, score REAL NOT NULL, payload_json TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS strategy_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER REFERENCES analysis_archives(id),
                generated_at TEXT NOT NULL, analysis_mode TEXT NOT NULL,
                market_data_mode TEXT NOT NULL, report_text TEXT NOT NULL, payload_json TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS node_execution_logs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT NOT NULL, node_name TEXT NOT NULL,
                status TEXT NOT NULL, mode TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
                duration_ms INTEGER, input_count INTEGER NOT NULL, output_count INTEGER NOT NULL,
                retry_count INTEGER NOT NULL, error TEXT NOT NULL, output_json TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS scheduler_config(
                id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
                config_json TEXT NOT NULL, updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS scheduler_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL, planned_at TEXT NOT NULL,
                started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
                status TEXT NOT NULL, detail_json TEXT NOT NULL, error TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_collection_batches_time ON collection_batches(captured_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_raw_topics_batch ON raw_topics(batch_id, ordinal)",
            "CREATE INDEX IF NOT EXISTS idx_raw_articles_batch ON raw_articles(batch_id, ordinal)",
            "CREATE INDEX IF NOT EXISTS idx_analysis_archives_time ON analysis_archives(completed_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_industry_results_analysis ON industry_analysis_results(analysis_id, result_type)",
            "CREATE INDEX IF NOT EXISTS idx_sentiment_results_analysis ON sentiment_results(analysis_id)",
            "CREATE INDEX IF NOT EXISTS idx_strategy_snapshots_time ON strategy_snapshots(generated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_node_logs_node_time ON node_execution_logs(node_id, id DESC)",
            "CREATE INDEX IF NOT EXISTS idx_scheduler_runs_time ON scheduler_runs(started_at DESC)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduler_runs_plan ON scheduler_runs(job_id, planned_at)",
        ]
        with self._lock, closing(self._connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            for statement in statements:
                db.execute(statement)
            db.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)", (str(self.SCHEMA_VERSION),))
            db.execute("PRAGMA optimize")

    def save_state(self, state: Mapping[str, Any]) -> None:
        now = str(state.get("updated_at") or datetime.now(timezone.utc).isoformat())
        payload = json.dumps(dict(state), ensure_ascii=False, separators=(",", ":"))
        with self._lock, closing(self._connect()) as db, db:
            db.execute("""INSERT INTO service_state(id,updated_at,stage,state_json) VALUES(1,?,?,?)
                ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,stage=excluded.stage,state_json=excluded.state_json""",
                (now, str(state.get("stage") or "idle"), payload))

    def load_state(self) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as db:
            row = db.execute("SELECT state_json FROM service_state WHERE id=1").fetchone()
        if not row:
            return None
        try:
            value = json.loads(str(row["state_json"]))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    def save_collection(self, topics: Sequence[Mapping[str, Any]], articles: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]) -> int:
        captured_at = str(summary.get("collected_at") or datetime.now(timezone.utc).isoformat())
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("INSERT INTO collection_batches(captured_at,guba_count,article_count,status,source_summary_json) VALUES(?,?,?,?,?)",
                (captured_at, len(topics), len(articles), "success", json.dumps(dict(summary), ensure_ascii=False)))
            batch_id = int(cursor.lastrowid)
            db.executemany("INSERT INTO raw_topics(batch_id,ordinal,title,url,read_count,comment_count,payload_json) VALUES(?,?,?,?,?,?,?)", [
                (batch_id, index, str(item.get("title") or ""), str(item.get("url") or ""), self._number(item.get("read_count")), self._number(item.get("comment_count")), json.dumps(dict(item), ensure_ascii=False))
                for index, item in enumerate(topics, start=1)
            ])
            db.executemany("INSERT INTO raw_articles(batch_id,ordinal,title,url,published_at,payload_json) VALUES(?,?,?,?,?,?)", [
                (batch_id, index, str(item.get("title") or ""), str(item.get("url") or ""), str(item.get("time") or ""), json.dumps(dict(item), ensure_ascii=False))
                for index, item in enumerate(articles, start=1)
            ])
        return batch_id

    def save_analysis(self, state: Mapping[str, Any]) -> int:
        mode = str((state.get("analysis_metadata") or {}).get("mode") or "unknown")
        completed = str(state.get("analysis_completed_at") or datetime.now(timezone.utc).isoformat())
        result_keys = ("guba_industries", "commentary_industries", "combined_industries", "industry_network", "industry_sentiments", "industry_research_capital")
        result = {key: state.get(key) for key in result_keys}
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("INSERT INTO analysis_archives(collection_batch_id,completed_at,analysis_mode,result_json) VALUES(?,?,?,?)",
                (state.get("collection_batch_id"), completed, mode, json.dumps(result, ensure_ascii=False)))
            analysis_id = int(cursor.lastrowid)
            rows = []
            for result_type in ("guba_industries", "commentary_industries", "combined_industries", "industry_research_capital"):
                for item in self._records(state.get(result_type)):
                    rows.append((analysis_id, result_type, str(item.get("industry") or ""), json.dumps(dict(item), ensure_ascii=False)))
            db.executemany("INSERT INTO industry_analysis_results(analysis_id,result_type,industry,payload_json) VALUES(?,?,?,?)", rows)
            db.executemany("INSERT INTO sentiment_results(analysis_id,industry,sentiment,score,payload_json) VALUES(?,?,?,?,?)", [
                (analysis_id, str(item.get("industry") or ""), str(item.get("sentiment") or ""), self._number(item.get("sentiment_score")), json.dumps(dict(item), ensure_ascii=False))
                for item in self._records(state.get("industry_sentiments"))
            ])
            metadata = state.get("strategy_metadata") if isinstance(state.get("strategy_metadata"), Mapping) else {}
            db.execute("INSERT INTO strategy_snapshots(analysis_id,generated_at,analysis_mode,market_data_mode,report_text,payload_json) VALUES(?,?,?,?,?,?)", (
                analysis_id, completed, mode, str(metadata.get("market_data_mode") or "unknown"),
                str(state.get("trading_strategy") or ""), json.dumps(dict(metadata), ensure_ascii=False),
            ))
        return analysis_id

    def save_node_log(self, node: Mapping[str, Any]) -> int:
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("""INSERT INTO node_execution_logs(node_id,node_name,status,mode,started_at,ended_at,duration_ms,input_count,output_count,retry_count,error,output_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                str(node.get("id") or ""), str(node.get("name") or ""), str(node.get("status") or ""), str(node.get("mode") or ""),
                str(node.get("started_at") or ""), str(node.get("ended_at") or ""), node.get("duration_ms"), int(node.get("input_count") or 0),
                int(node.get("output_count") or 0), int(node.get("retry_count") or 0), str(node.get("error") or ""), json.dumps(node.get("output") or {}, ensure_ascii=False),
            ))
        return int(cursor.lastrowid)

    def load_scheduler_config(self, defaults: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as db:
            row = db.execute("SELECT enabled,config_json FROM scheduler_config WHERE id=1").fetchone()
        if not row:
            config = dict(defaults)
            self.save_scheduler_config(config)
            return config
        try:
            stored = json.loads(str(row["config_json"]))
        except json.JSONDecodeError:
            stored = {}
        config = {**dict(defaults), **(stored if isinstance(stored, dict) else {})}
        config["enabled"] = bool(row["enabled"])
        return config

    def save_scheduler_config(self, config: Mapping[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload = dict(config)
        enabled = bool(payload.get("enabled", True))
        with self._lock, closing(self._connect()) as db, db:
            db.execute("""INSERT INTO scheduler_config(id,enabled,config_json,updated_at) VALUES(1,?,?,?)
                ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled,config_json=excluded.config_json,updated_at=excluded.updated_at""",
                (int(enabled), json.dumps(payload, ensure_ascii=False), now))

    def has_scheduler_run(self, job_id: str, planned_at: str) -> bool:
        with self._lock, closing(self._connect()) as db:
            row = db.execute("SELECT 1 FROM scheduler_runs WHERE job_id=? AND planned_at=?", (job_id, planned_at)).fetchone()
        return bool(row)

    def save_scheduler_run(self, *, job_id: str, trigger_type: str, planned_at: str,
                           started_at: str, ended_at: str, status: str,
                           detail: Mapping[str, Any] | None = None, error: str = "") -> int:
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("""INSERT OR IGNORE INTO scheduler_runs(
                job_id,trigger_type,planned_at,started_at,ended_at,status,detail_json,error
            ) VALUES(?,?,?,?,?,?,?,?)""", (job_id, trigger_type, planned_at, started_at, ended_at, status,
                json.dumps(dict(detail or {}), ensure_ascii=False), error[:600]))
        return int(cursor.lastrowid or 0)

    def recent_scheduler_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM scheduler_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["detail"] = json.loads(item.pop("detail_json"))
            except (json.JSONDecodeError, TypeError):
                item["detail"] = {}
            result.append(item)
        return result

    def admin_overview(self, limit: int = 30) -> dict[str, Any]:
        """Read-only operational view; intentionally exposes no SQL execution surface."""
        safe_limit = max(1, min(limit, 100))
        with self._lock, closing(self._connect()) as db:
            journal_mode = str(db.execute("PRAGMA journal_mode").fetchone()[0])
            batches = [dict(row) for row in db.execute(
                "SELECT id,captured_at,guba_count,article_count,status FROM collection_batches ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()]
            logs = [dict(row) for row in db.execute(
                """SELECT id,node_id,node_name,status,mode,started_at,ended_at,duration_ms,
                    input_count,output_count,retry_count,error
                    FROM node_execution_logs ORDER BY id DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()]
        return {
            "database_path": str(self.path),
            "database_size_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "journal_mode": journal_mode,
            "recent_batches": batches,
            "recent_node_logs": logs,
            "read_only_console": True,
        }

    def status(self) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as db:
            counts = {table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in (
                "collection_batches", "raw_topics", "raw_articles", "analysis_archives", "industry_analysis_results",
                "sentiment_results", "strategy_snapshots", "node_execution_logs", "scheduler_runs",
            )}
            state_row = db.execute("SELECT updated_at,stage FROM service_state WHERE id=1").fetchone()
        return {"enabled": True, "engine": "SQLite", "schema_version": self.SCHEMA_VERSION, "database_file": self.path.name,
                "state_restored": bool(state_row), "last_persisted_at": str(state_row["updated_at"]) if state_row else "", "last_stage": str(state_row["stage"]) if state_row else "", "counts": counts,
                "postgresql_ready": True, "migration_note": "表已按批次、分析、策略和节点日志分层，后续可迁移 PostgreSQL。"}

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0)
        except (TypeError, ValueError, OverflowError): return 0.0
