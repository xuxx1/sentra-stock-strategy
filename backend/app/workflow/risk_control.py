"""从确定性交易计划生成组合风险指标和情景压力测试。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


class RiskControlBuilder:
    TOTAL_CAPITAL = 10_000.0
    NEGATIVE_WORDS = ("减持", "下调", "亏损", "风险", "回调", "暴跌", "处罚", "诉讼", "承压", "利空")

    def build(self, state: Mapping[str, Any], trust: Mapping[str, Any], trends: Mapping[str, Any]) -> dict[str, Any]:
        metadata = state.get("strategy_metadata") if isinstance(state.get("strategy_metadata"), Mapping) else {}
        plans = self._records(metadata.get("trade_plans"))
        if not plans:
            return {"available": False, "message": "生成策略报告后计算组合风险"}
        total = float(metadata.get("total_capital") or self.TOTAL_CAPITAL)
        cash = float(metadata.get("cash_reserve") or 0)
        invested = sum(self._number(item.get("planned_amount")) for item in plans)
        industry_amounts: dict[str, float] = {}
        loss_amounts: list[dict[str, Any]] = []
        expected_profit = 0.0
        max_loss = 0.0
        optimistic_profit = 0.0
        for item in plans:
            amount = self._number(item.get("planned_amount"))
            industry = str(item.get("industry") or "")
            industry_amounts[industry] = industry_amounts.get(industry, 0) + amount
            midpoint = (self._number(item.get("buy_low")) + self._number(item.get("buy_high"))) / 2
            shares = self._number(item.get("shares"))
            loss = max(0, (midpoint - self._number(item.get("stop_price"))) * shares)
            max_loss += loss
            base_return = (self._number(item.get("potential_return_low")) + self._number(item.get("potential_return_high"))) / 2
            expected_profit += amount * base_return / 100
            optimistic_profit += amount * self._number(item.get("potential_return_high")) / 100
            loss_amounts.append({
                "stock": item.get("stock"), "industry": industry, "position_amount": round(amount, 2),
                "position_pct": round(amount / total * 100, 2), "stop_price": item.get("stop_price"),
                "estimated_stop_loss": round(loss, 2),
            })
        weights = [self._number(item.get("planned_amount")) / invested for item in plans if invested]
        concentration = round(sum(weight * weight for weight in weights) * 100, 2)
        sentiment_alerts = self._sentiment_alerts(trends)
        cooling = [str(item.get("industry")) for item in self._records(trends.get("industries")) if any("降温" in str(tag) or "回落" in str(tag) for tag in item.get("tags", []))]
        negative_news = self._negative_news(self._records(state.get("guba_topics")) + self._records(state.get("finance_commentary")))
        stale_sources = [str(item.get("name")) for item in self._records(trust.get("sources")) if item.get("freshness") in {"stale", "warning", "unknown", "not_run"}]
        simulated = bool(metadata.get("is_simulation"))
        alerts = []
        alerts.extend({"level": "high", "type": "舆情反转", "message": message} for message in sentiment_alerts)
        if cooling: alerts.append({"level": "medium", "type": "热点衰退", "message": f"{'、'.join(cooling[:4])}出现降温或回落信号"})
        if negative_news: alerts.append({"level": "medium", "type": "负面新闻", "message": f"本批次识别 {negative_news} 条含风险词内容"})
        if stale_sources: alerts.append({"level": "high", "type": "数据过期", "message": f"{'、'.join(stale_sources)}新鲜度不足"})
        if simulated: alerts.append({"level": "medium", "type": "模拟行情", "message": "价格、研报和资金流为模拟数据，禁止直接据此实盘下单"})
        return {
            "available": True, "total_capital": total, "invested_amount": round(invested, 2), "remaining_cash": round(cash, 2),
            "max_stock_position_pct": round(max(self._number(item.get("planned_amount")) for item in plans) / total * 100, 2),
            "max_industry_position_pct": round(max(industry_amounts.values()) / total * 100, 2),
            "concentration_index": concentration,
            "concentration_level": "高" if concentration >= 35 else "中" if concentration >= 25 else "低",
            "expected_return_pct": round(expected_profit / total * 100, 2),
            "max_risk_pct": round(max_loss / total * 100, 2), "max_risk_amount": round(max_loss, 2),
            "reward_risk_ratio": round(expected_profit / max_loss, 2) if max_loss else None,
            "negative_news_count": negative_news, "stock_risks": loss_amounts, "industry_positions": [{"industry": key, "amount": round(value, 2), "position_pct": round(value / total * 100, 2)} for key, value in industry_amounts.items()],
            "alerts": alerts,
            "scenarios": [
                {"name": "乐观", "result_pct": round(optimistic_profit / total * 100, 2), "result_amount": round(optimistic_profit, 2), "advice": "到达目标区间后分批止盈"},
                {"name": "基准", "result_pct": round(expected_profit / total * 100, 2), "result_amount": round(expected_profit, 2), "advice": "信号未反转时按计划持有"},
                {"name": "悲观", "result_pct": round(-max_loss / total * 100, 2), "result_amount": round(-max_loss, 2), "advice": "触及风险退出价立即止损"},
            ],
            "calculation_note": "仓位按计划金额/1万元计算；最大风险按买入区间中值至止损价测算；情景结果不代表收益承诺。",
        }

    def _sentiment_alerts(self, trends: Mapping[str, Any]) -> list[str]:
        alerts = []
        for item in self._records(trends.get("industries")):
            points = self._records(item.get("points"))
            if len(points) >= 2 and self._number(points[-1].get("sentiment_score")) <= self._number(points[-2].get("sentiment_score")) - 8:
                alerts.append(f"{item.get('industry')}情绪分单次下降超过8分")
        return alerts

    def _negative_news(self, rows: list[Mapping[str, Any]]) -> int:
        return sum(any(word in f"{item.get('title', '')} {item.get('content', '')}" for word in self.NEGATIVE_WORDS) for item in rows)

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0)
        except (TypeError, ValueError, OverflowError): return 0.0
