"""策略执行看板：默认且仅进行模拟状态跟踪。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence


class StrategyExecutionBoardBuilder:
    def build(self, state: Mapping[str, Any]) -> dict[str, Any]:
        metadata = state.get("strategy_metadata") if isinstance(state.get("strategy_metadata"), Mapping) else {}
        plans = self._records(metadata.get("trade_plans"))
        pool = state.get("stock_candidate_pool") if isinstance(state.get("stock_candidate_pool"), Mapping) else {}
        quotes = {str(item.get("stock") or ""): item for item in self._records(pool.get("stocks"))}
        if not plans:
            return {"available": False, "execution_mode": "paper", "broker_connected": False, "positions": [], "message": "生成策略后建立模拟执行看板"}
        generated_date = self._date(str(metadata.get("as_of_date") or state.get("analysis_date") or date.today().isoformat()))
        today = date.today()
        elapsed = self._trading_days_after(generated_date, today)
        remaining = max(0, 5 - elapsed)
        positions = []
        for plan in plans:
            stock = str(plan.get("stock") or "")
            current = self._number(quotes.get(stock, {}).get("current_price") or plan.get("current_price"))
            buy_low, buy_high = self._number(plan.get("buy_low")), self._number(plan.get("buy_high"))
            stop = self._number(plan.get("stop_price"))
            target_low, target_high = self._number(plan.get("target_low")), self._number(plan.get("target_high"))
            entry = round((buy_low + buy_high) / 2, 2)
            entered = buy_low <= current <= buy_high or (elapsed > 0 and stop < current < target_low)
            hit_stop = entered and current <= stop
            hit_target = entered and current >= target_low
            expired = elapsed >= 5 and not hit_target
            if hit_stop:
                status, action = "已失效", "触及止损价，模拟退出并停止继续持有"
            elif hit_target:
                status, action = "已触发", "进入目标区间，分批模拟止盈"
            elif expired:
                status, action = "已失效", "已到第5个交易日，按纪律模拟退出"
            elif entered:
                status, action = "已触发", "继续模拟持有；监控止损、目标和舆情反转"
            elif current > buy_high:
                status, action = "未触发", "价格高于买入区间，今日不追涨"
            else:
                status, action = "未触发", "价格低于买入区间，等待企稳并重新确认信号"
            floating_pct = round((current / entry - 1) * 100, 2) if entered else None
            amount = self._number(plan.get("planned_amount"))
            positions.append({
                "industry": plan.get("industry"), "stock": stock, "status": status, "today_action": action,
                "in_buy_range": buy_low <= current <= buy_high, "current_price": current,
                "simulated_entry_price": entry if entered else None, "planned_amount": amount,
                "floating_return_pct": floating_pct,
                "floating_profit_amount": round(amount * floating_pct / 100, 2) if floating_pct is not None else None,
                "buy_range": [buy_low, buy_high], "stop_price": stop, "target_range": [target_low, target_high],
                "distance_to_stop_pct": round((current / stop - 1) * 100, 2) if stop else None,
                "distance_to_target_pct": round((target_low / current - 1) * 100, 2) if current else None,
                "elapsed_trading_days": elapsed, "remaining_holding_days": remaining,
                "day5_exit_reminder": "今日为第5日或已超期，执行模拟退出" if remaining == 0 else f"距离第5日退出还有 {remaining} 个交易日",
            })
        triggered = [item for item in positions if item["status"] == "已触发"]
        invalid = [item for item in positions if item["status"] == "已失效"]
        pending = [item for item in positions if item["status"] == "未触发"]
        if invalid:
            today_summary = f"处理 {len(invalid)} 个失效/退出信号，并复核剩余模拟持仓"
        elif triggered:
            today_summary = f"管理 {len(triggered)} 个已触发模拟持仓，严格执行止损和目标区间"
        else:
            today_summary = f"等待 {len(pending)} 个买入信号，不追涨、不提前成交"
        total_profit = round(sum(item["floating_profit_amount"] or 0 for item in positions), 2)
        invested = sum(item["planned_amount"] for item in positions if item["status"] == "已触发")
        return {
            "available": True, "execution_mode": "paper", "broker_connected": False,
            "market_data_mode": str(pool.get("market_data_mode") or metadata.get("market_data_mode") or "unknown"),
            "generated_date": generated_date.isoformat(), "current_date": today.isoformat(),
            "today_summary": today_summary, "triggered_count": len(triggered), "pending_count": len(pending),
            "invalid_count": len(invalid), "remaining_holding_days": remaining,
            "portfolio_floating_profit": total_profit,
            "portfolio_floating_return_pct": round(total_profit / invested * 100, 2) if invested else None,
            "positions": positions,
            "day5_reminder": "今日执行第5日模拟退出" if remaining == 0 else f"第5个交易日统一复核退出，剩余 {remaining} 个交易日",
            "disclaimer": "当前仅为模拟交易跟踪，不连接券商、不发送委托；真实交易必须另行接入并获得明确授权。",
        }

    @staticmethod
    def _trading_days_after(start: date, end: date) -> int:
        if end <= start: return 0
        days, cursor = 0, start
        while cursor < end:
            cursor = date.fromordinal(cursor.toordinal() + 1)
            if cursor.weekday() < 5: days += 1
        return days

    @staticmethod
    def _date(value: str) -> date:
        try: return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError: return date.today()

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0)
        except (TypeError, ValueError, OverflowError): return 0.0
