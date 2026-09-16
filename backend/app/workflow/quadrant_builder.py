"""行业资金/舆情四象限的确定性坐标构建。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


class IndustryQuadrantBuilder:
    THRESHOLD = 60
    FLOW_SCORES = {
        "净流入": 82, "持续流入": 92, "震荡流入": 70,
        "资金平衡": 50, "震荡流出": 30, "持续流出": 10, "净流出": 18,
    }

    def build(self, state: Mapping[str, Any]) -> dict[str, Any]:
        industries = self._records(state.get("combined_industries"))
        sentiments = {str(item.get("industry") or ""): item for item in self._records(state.get("industry_sentiments"))}
        capital = {str(item.get("industry") or ""): item for item in self._records(state.get("industry_research_capital"))}
        mode = str((state.get("research_capital_metadata") or {}).get("data_mode") or "unknown")
        points = []
        for item in industries:
            name = str(item.get("industry") or "")
            sentiment = sentiments.get(name, {})
            funding = capital.get(name, {})
            flow = funding.get("capital_flow") if isinstance(funding.get("capital_flow"), Mapping) else {}
            today = self.FLOW_SCORES.get(str(flow.get("today") or ""), 50)
            five = self.FLOW_SCORES.get(str(flow.get("five_days") or ""), 50)
            ten = self.FLOW_SCORES.get(str(flow.get("ten_days") or ""), 50)
            capital_score = round(today * 0.25 + five * 0.45 + ten * 0.30, 1)
            market = self._number(item.get("market_hot_score"))
            sentiment_score = self._number(sentiment.get("sentiment_score"))
            public_opinion = round(market * 0.65 + sentiment_score * 0.35, 1)
            points.append({
                "industry": name, "capital_score": capital_score, "public_opinion_score": public_opinion,
                "combined_heat": self._number(item.get("combined_score")),
                "sentiment": str(sentiment.get("sentiment") or "neutral"),
                "sentiment_score": sentiment_score, "capital_flow": dict(flow),
                "quadrant": self._quadrant(capital_score, public_opinion),
            })
        return {
            "available": bool(points), "capital_data_mode": mode, "threshold": self.THRESHOLD,
            "points": points,
            "axis_formula": {
                "capital": "今日资金×25% + 5日趋势×45% + 10日趋势×30%",
                "public_opinion": "股吧市场热度×65% + 行业情绪分×35%",
                "bubble": "气泡大小 = 综合热度；颜色 = 情绪方向",
            },
        }

    def _quadrant(self, x: float, y: float) -> str:
        if y >= self.THRESHOLD and x >= self.THRESHOLD: return "重点观察"
        if y >= self.THRESHOLD and x < self.THRESHOLD: return "可能炒作"
        if y < self.THRESHOLD and x >= self.THRESHOLD: return "资金先行"
        return "低优先级"

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0)
        except (TypeError, ValueError, OverflowError): return 0.0
