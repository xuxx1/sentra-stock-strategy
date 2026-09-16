"""舆情、资金、政策和候选股票的背离监控。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


class SentimentCapitalDivergenceBuilder:
    """输出可审计的背离事件；需要历史数据的规则在基线不足时不触发。"""

    def build(
        self,
        state: Mapping[str, Any],
        trends: Mapping[str, Any],
        burst: Mapping[str, Any],
        quadrant: Mapping[str, Any],
    ) -> dict[str, Any]:
        industries = {str(item.get("industry") or ""): item for item in self._records(state.get("combined_industries"))}
        capital = {str(item.get("industry") or ""): item for item in self._records(state.get("industry_research_capital"))}
        evidence = {str(item.get("industry") or ""): item for item in self._records(state.get("strategy_evidence"))}
        trend_map = {str(item.get("industry") or ""): item for item in self._records(trends.get("industries"))}
        quadrant_map = {str(item.get("industry") or ""): item for item in self._records(quadrant.get("points"))}
        burst_map = {str(item.get("industry") or ""): item for item in self._records(burst.get("industries"))}
        trend_ready = int(trends.get("sample_count") or 0) >= 2
        burst_ready = bool(burst.get("ready"))
        alerts: list[dict[str, Any]] = []

        for name, item in industries.items():
            alert_start = len(alerts)
            market = self._number(item.get("market_hot_score"))
            policy = self._number(item.get("policy_support_score"))
            heat = self._number(item.get("combined_score"))
            point = quadrant_map.get(name, {})
            capital_score = self._number(point.get("capital_score"))
            flow = capital.get(name, {}).get("capital_flow", {})
            flow = flow if isinstance(flow, Mapping) else {}
            trend = trend_map.get(name, {})
            points = self._records(trend.get("points"))
            opinion_change = self._opinion_change(points)
            tags = [str(tag) for tag in trend.get("tags", [])]

            if trend_ready and opinion_change is not None and opinion_change >= 5 and self._is_outflow(flow, capital_score):
                alerts.append(self._alert(name, "舆情升温但资金流出", "high", opinion_change, capital_score,
                    f"舆情合成分上升 {opinion_change:+.1f}，资金强度仅 {capital_score:.1f}",
                    "警惕热度缺少资金确认，避免追高；等待资金止跌或重新流入。",
                    ["行业趋势快照", "资金流向"]))

            cooling = opinion_change is not None and opinion_change <= -5 or any("降温" in tag or "回落" in tag for tag in tags)
            if trend_ready and cooling and self._is_inflow(flow, capital_score):
                alerts.append(self._alert(name, "舆情降温但资金流入", "medium", opinion_change, capital_score,
                    f"舆情合成分变化 {opinion_change or 0:+.1f}，资金强度 {capital_score:.1f}",
                    "可能是资金先行或逆势承接，关注后续舆情是否止跌回升。",
                    ["行业趋势快照", "资金流向"]))

            if policy >= 75 and (market < 60 or policy - market >= 20):
                alerts.append(self._alert(name, "政策热度高但市场不响应", "medium", policy, market,
                    f"政策热度 {policy:.0f}，市场热度 {market:.0f}，差值 {policy - market:+.0f}",
                    "政策逻辑尚未转化为市场共识，等待讨论量和资金同步改善。",
                    ["政策分析", "股吧热度"]))

            news_growth = burst_map.get(name, {}).get("news_growth_rate")
            if burst_ready and market >= 85 and news_growth is not None and self._number(news_growth) >= 20:
                alerts.append(self._alert(name, "股吧极度乐观但负面新闻增加", "high", market, self._number(news_growth),
                    f"股吧热度 {market:.0f}，新闻数量增长 {self._number(news_growth):+.1f}%",
                    "穿透核验新增新闻的风险词和来源，必要时降低仓位。",
                    ["股吧热度", "周期新闻快照"]))

            chain = evidence.get(name, {})
            candidates = capital.get(name, {}).get("top_capital_stocks", [])
            candidates = candidates if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes)) else []
            selected = chain.get("selected_stocks", [])
            selected = selected if isinstance(selected, Sequence) and not isinstance(selected, (str, bytes)) else []
            is_recommended = bool(chain.get("recommended"))
            mismatch = not candidates or (is_recommended and (not selected or any(stock not in candidates for stock in selected)))
            if heat >= 75 and mismatch:
                alerts.append(self._alert(name, "行业热度高但推荐股票无法匹配", "high", heat, len(candidates),
                    f"行业综合热度 {heat:.0f}，可校验资金候选 {len(candidates)} 只",
                    "暂停生成该行业交易指令，补齐股票映射和资金候选后重新运行策略节点。",
                    ["行业融合", "资金候选池", "策略证据链"]))
            for alert in alerts[alert_start:]:
                alert["industry_heat"] = heat

        alerts.sort(key=lambda item: ({"high": 0, "medium": 1, "low": 2}.get(item["severity"], 3), -item["industry_heat"], item["industry"]))
        counts: dict[str, int] = {}
        for item in alerts: counts[item["type"]] = counts.get(item["type"], 0) + 1
        return {
            "available": bool(industries), "alert_count": len(alerts),
            "high_count": sum(item["severity"] == "high" for item in alerts),
            "capital_data_mode": str(quadrant.get("capital_data_mode") or "unknown"),
            "trend_baseline_ready": trend_ready, "news_baseline_ready": burst_ready,
            "alerts": alerts, "counts_by_type": counts,
            "rules": [
                {"type": "舆情升温但资金流出", "requires_history": True, "threshold": "舆情合成分较上次上升≥5，且资金强度<45或出现流出"},
                {"type": "舆情降温但资金流入", "requires_history": True, "threshold": "舆情合成分下降≥5/出现降温标签，且资金强度≥60或持续流入"},
                {"type": "政策热度高但市场不响应", "requires_history": False, "threshold": "政策热度≥75，且市场热度<60或两者差值≥20"},
                {"type": "股吧极度乐观但负面新闻增加", "requires_history": True, "threshold": "股吧热度≥85，且新闻数量增长≥20%"},
                {"type": "行业热度高但推荐股票无法匹配", "requires_history": False, "threshold": "综合热度≥75，且无资金候选或推荐股票不在候选池"},
            ],
            "message": "背离越强越需要复核，并不等同于自动买卖信号。",
        }

    @staticmethod
    def _opinion_change(points: list[Mapping[str, Any]]) -> float | None:
        if len(points) < 2: return None
        def score(point: Mapping[str, Any]) -> float:
            return float(point.get("market_hot_score") or 0) * 0.65 + float(point.get("sentiment_score") or 0) * 0.35
        return round(score(points[-1]) - score(points[-2]), 1)

    @staticmethod
    def _is_outflow(flow: Mapping[str, Any], score: float) -> bool:
        return score < 45 or any("流出" in str(flow.get(key) or "") for key in ("today", "five_days", "ten_days"))

    @staticmethod
    def _is_inflow(flow: Mapping[str, Any], score: float) -> bool:
        return score >= 60 or any("流入" in str(flow.get(key) or "") for key in ("today", "five_days", "ten_days"))

    def _alert(self, industry: str, kind: str, severity: str, signal_a: Any, signal_b: Any, evidence: str, action: str, sources: list[str]) -> dict[str, Any]:
        return {"industry": industry, "type": kind, "severity": severity, "signal_a": signal_a, "signal_b": signal_b, "evidence": evidence, "action": action, "sources": sources, "industry_heat": 0}

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0)
        except (TypeError, ValueError, OverflowError): return 0.0
