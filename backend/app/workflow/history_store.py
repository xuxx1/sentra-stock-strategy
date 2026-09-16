"""策略快照、真实表现观察和回测汇总。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class StrategyHistoryStore:
    """只有真实入场行情才进入绩效统计，模拟计划仅归档、不计胜率。"""

    STOCK_CODES = {
        "中科曙光": "1.603019", "浪潮信息": "0.000977", "中际旭创": "0.300308",
        "北方华创": "0.002371", "中微公司": "1.688012", "海光信息": "1.688041",
        "三花智控": "0.002050", "拓普集团": "1.601689", "绿的谐波": "1.688017",
        "比亚迪": "0.002594", "宁德时代": "0.300750", "汇川技术": "0.300124",
        "美的集团": "0.000333", "海尔智家": "1.600690", "伊利股份": "1.600887",
        "招商银行": "1.600036", "工商银行": "1.601398", "宁波银行": "0.002142",
        "恒瑞医药": "1.600276", "药明康德": "1.603259", "华东医药": "0.000963",
        "中国石油": "1.601857", "中国神华": "1.601088", "阳光电源": "0.300274",
        "中航沈飞": "1.600760", "航发动力": "1.600893", "中航西飞": "0.000768",
    }

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
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("""CREATE TABLE IF NOT EXISTS strategy_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL UNIQUE,
                generated_at TEXT NOT NULL, analysis_date TEXT NOT NULL, analysis_mode TEXT NOT NULL,
                market_data_mode TEXT NOT NULL, status TEXT NOT NULL, context_json TEXT NOT NULL,
                recommendations_json TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS strategy_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES strategy_runs(id) ON DELETE CASCADE,
                industry TEXT NOT NULL, stock TEXT NOT NULL, stock_code TEXT, entry_price REAL NOT NULL,
                buy_low REAL NOT NULL, buy_high REAL NOT NULL, target_low REAL NOT NULL, target_high REAL NOT NULL,
                stop_price REAL NOT NULL, planned_amount REAL NOT NULL, entry_data_mode TEXT NOT NULL,
                day1_return REAL, day3_return REAL, day5_return REAL, max_up REAL, max_drawdown REAL,
                hit_target INTEGER, hit_stop INTEGER, observed_days INTEGER NOT NULL DEFAULT 0,
                actual_source TEXT, last_checked_at TEXT, evaluation_error TEXT,
                UNIQUE(run_id, stock)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_strategy_runs_generated ON strategy_runs(generated_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_strategy_positions_run ON strategy_positions(run_id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_strategy_positions_pending ON strategy_positions(entry_data_mode, observed_days)")
            db.execute("PRAGMA optimize")

    def archive(self, state: Mapping[str, Any]) -> int | None:
        meta = state.get("strategy_metadata") if isinstance(state.get("strategy_metadata"), Mapping) else {}
        plans = self._records(meta.get("trade_plans"))
        if not plans:
            return None
        generated = str(state.get("analysis_completed_at") or datetime.now(timezone.utc).isoformat())
        mode = str((state.get("analysis_metadata") or {}).get("mode") or meta.get("analysis_mode") or "unknown")
        market_mode = str(meta.get("market_data_mode") or "unknown")
        fingerprint = hashlib.sha256(f"{generated}|{mode}|{json.dumps(plans, ensure_ascii=False, sort_keys=True)}".encode()).hexdigest()
        context = {
            "guba_topics": state.get("guba_topics", []), "finance_commentary": state.get("finance_commentary", []),
            "combined_industries": state.get("combined_industries", []), "industry_network": state.get("industry_network", {}),
            "industry_sentiments": state.get("industry_sentiments", []), "industry_research_capital": state.get("industry_research_capital", []),
            "strategy_evidence": state.get("strategy_evidence", []),
        }
        status = "pending_actual" if market_mode == "real" else "simulation_only"
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("""INSERT OR IGNORE INTO strategy_runs(
                fingerprint, generated_at, analysis_date, analysis_mode, market_data_mode, status, context_json, recommendations_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                fingerprint, generated, str(state.get("analysis_date") or ""), mode, market_mode, status,
                json.dumps(context, ensure_ascii=False), json.dumps(meta.get("recommendations", []), ensure_ascii=False),
            ))
            if not cursor.rowcount:
                row = db.execute("SELECT id FROM strategy_runs WHERE fingerprint=?", (fingerprint,)).fetchone()
                return int(row["id"]) if row else None
            run_id = int(cursor.lastrowid)
            db.executemany("""INSERT INTO strategy_positions(
                run_id, industry, stock, stock_code, entry_price, buy_low, buy_high, target_low, target_high,
                stop_price, planned_amount, entry_data_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", [(
                run_id, str(item.get("industry") or ""), str(item.get("stock") or ""), self.STOCK_CODES.get(str(item.get("stock") or "")),
                self._number(item.get("current_price")), self._number(item.get("buy_low")), self._number(item.get("buy_high")),
                self._number(item.get("target_low")), self._number(item.get("target_high")), self._number(item.get("stop_price")),
                self._number(item.get("planned_amount")), market_mode,
            ) for item in plans])
        return run_id

    def summary(self, limit: int = 30) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as db:
            runs = db.execute("SELECT * FROM strategy_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            if not runs:
                return self._empty()
            ids = [int(row["id"]) for row in runs]
            marks = ",".join("?" for _ in ids)
            positions = db.execute(f"SELECT * FROM strategy_positions WHERE run_id IN ({marks}) ORDER BY run_id DESC, id", ids).fetchall()
        by_run: dict[int, list[sqlite3.Row]] = {}
        for row in positions: by_run.setdefault(int(row["run_id"]), []).append(row)
        verified_positions = [row for row in positions if row["day5_return"] is not None and row["entry_data_mode"] == "real"]
        completed_runs = []
        for run in runs:
            rows = by_run.get(int(run["id"]), [])
            verified = [row for row in rows if row["day5_return"] is not None and row["entry_data_mode"] == "real"]
            if rows and len(verified) == len(rows):
                completed_runs.append({"run": run, "return": self._weighted_return(verified), "drawdown": self._weighted_metric(verified, "max_drawdown")})
        returns = [item["return"] for item in completed_runs]
        wins = [value for value in returns if value > 0]
        losses = [value for value in returns if value < 0]
        industry: dict[str, list[float]] = {}
        for row in verified_positions: industry.setdefault(str(row["industry"]), []).append(float(row["day5_return"]))
        mode_stats = []
        for mode in ("rule_based", "rule_based_fallback", "openai"):
            values = [item["return"] for item in completed_runs if item["run"]["analysis_mode"] == mode]
            mode_stats.append({"mode": mode, "verified_count": len(values), "win_rate": round(sum(v > 0 for v in values) / len(values) * 100, 2) if values else None, "average_return": round(sum(values) / len(values), 2) if values else None})
        recent = []
        for run in runs[:10]:
            rows = by_run.get(int(run["id"]), [])
            recent.append({
                "id": int(run["id"]), "generated_at": str(run["generated_at"]), "analysis_mode": str(run["analysis_mode"]),
                "market_data_mode": str(run["market_data_mode"]), "status": str(run["status"]),
                "industries": list(dict.fromkeys(str(row["industry"]) for row in rows)), "stocks": [str(row["stock"]) for row in rows],
                "verified_days": min((int(row["observed_days"]) for row in rows), default=0),
            })
        failures = [{"run_id": int(item["run"]["id"]), "generated_at": str(item["run"]["generated_at"]), "return_pct": round(item["return"], 2), "reason": "5日组合收益为负，需穿透复盘舆情、入场与止损纪律"} for item in completed_runs if item["return"] <= 0][:5]
        return {
            "archived_count": len(runs), "verified_5d_count": len(completed_runs), "pending_count": sum(row["status"] == "pending_actual" for row in runs),
            "simulation_only_count": sum(row["status"] == "simulation_only" for row in runs),
            "win_rate": round(len(wins) / len(returns) * 100, 2) if returns else None,
            "average_5d_return": round(sum(returns) / len(returns), 2) if returns else None,
            "average_max_drawdown": round(sum(item["drawdown"] for item in completed_runs) / len(completed_runs), 2) if completed_runs else None,
            "profit_loss_ratio": round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)), 2) if wins and losses else None,
            "industry_performance": [{"industry": key, "samples": len(values), "average_return": round(sum(values) / len(values), 2), "win_rate": round(sum(v > 0 for v in values) / len(values) * 100, 2)} for key, values in sorted(industry.items())],
            "mode_comparison": mode_stats,
            "excess_return": {"available": False, "value": None, "message": "基准指数真实行情尚未接入，不计算超额收益"},
            "recent_strategies": recent, "failure_cases": failures,
            "methodology": "仅统计生成时使用真实行情、且已取得第5个交易日实际收盘数据的策略；模拟行情档案不进入胜率和收益统计。",
        }

    def pending_positions(self) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as db:
            rows = db.execute("""SELECT p.*, r.analysis_date FROM strategy_positions p
                JOIN strategy_runs r ON r.id=p.run_id
                WHERE p.entry_data_mode='real' AND p.observed_days<5 ORDER BY p.id""").fetchall()
        return [dict(row) for row in rows]

    def save_observation(self, position_id: int, bars: Sequence[Mapping[str, Any]], *, source: str, error: str = "") -> None:
        if not bars:
            with self._lock, closing(self._connect()) as db, db:
                db.execute("UPDATE strategy_positions SET last_checked_at=?, actual_source=?, evaluation_error=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), source, error or "尚无到期交易日数据", position_id))
            return
        with self._lock, closing(self._connect()) as db:
            row = db.execute("SELECT * FROM strategy_positions WHERE id=?", (position_id,)).fetchone()
        if not row:
            return
        values = list(bars[:5])
        entry = float(row["entry_price"])
        returns = [round((self._number(item.get("close")) / entry - 1) * 100, 2) for item in values]
        max_up = round((max(self._number(item.get("high")) for item in values) / entry - 1) * 100, 2)
        max_drawdown = round((min(self._number(item.get("low")) for item in values) / entry - 1) * 100, 2)
        hit_target = any(self._number(item.get("high")) >= float(row["target_low"]) for item in values)
        hit_stop = any(self._number(item.get("low")) <= float(row["stop_price"]) for item in values)
        with self._lock, closing(self._connect()) as db, db:
            db.execute("""UPDATE strategy_positions SET day1_return=?, day3_return=?, day5_return=?,
                max_up=?, max_drawdown=?, hit_target=?, hit_stop=?, observed_days=?, actual_source=?,
                last_checked_at=?, evaluation_error=? WHERE id=?""", (
                returns[0] if len(returns) >= 1 else None, returns[2] if len(returns) >= 3 else None,
                returns[4] if len(returns) >= 5 else None, max_up, max_drawdown, int(hit_target), int(hit_stop),
                len(values), source, datetime.now(timezone.utc).isoformat(), error, position_id,
            ))
            if len(values) >= 5:
                db.execute("UPDATE strategy_runs SET status='verified_5d' WHERE id=? AND NOT EXISTS (SELECT 1 FROM strategy_positions WHERE run_id=? AND observed_days<5)", (int(row["run_id"]), int(row["run_id"])))

    @staticmethod
    def _weighted_return(rows: Sequence[sqlite3.Row]) -> float:
        total = sum(float(row["planned_amount"]) for row in rows)
        return sum(float(row["day5_return"]) * float(row["planned_amount"]) for row in rows) / total if total else 0.0

    @staticmethod
    def _weighted_metric(rows: Sequence[sqlite3.Row], key: str) -> float:
        total = sum(float(row["planned_amount"]) for row in rows)
        return sum(float(row[key] or 0) * float(row["planned_amount"]) for row in rows) / total if total else 0.0

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"archived_count": 0, "verified_5d_count": 0, "pending_count": 0, "simulation_only_count": 0, "win_rate": None, "average_5d_return": None, "average_max_drawdown": None, "profit_loss_ratio": None, "industry_performance": [], "mode_comparison": [], "excess_return": {"available": False, "message": "暂无数据"}, "recent_strategies": [], "failure_cases": [], "methodology": "策略生成后开始归档；只有真实行情样本进入绩效统计。"}

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0)
        except (TypeError, ValueError, OverflowError): return 0.0
