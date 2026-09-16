"""构建可排序、可穿透的个股候选池。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.app.providers import SimulatedMarketDataProvider


class StockCandidatePoolBuilder:
    def __init__(self, market_provider: Any | None = None) -> None:
        self.market = market_provider or SimulatedMarketDataProvider()

    async def build(self, state: Mapping[str, Any]) -> dict[str, Any]:
        capital = self._records(state.get("industry_research_capital"))
        names = list(dict.fromkeys(str(stock) for item in capital for stock in item.get("top_capital_stocks", []) if stock))
        if not names:
            return {"available": False, "market_data_mode": "unknown", "stocks": [], "message": "资金整合后生成候选池"}
        quotes = await self.market.fetch_quotes(names, as_of_date=str(state.get("analysis_date") or ""))
        industries = {str(item.get("industry") or ""): item for item in self._records(state.get("combined_industries"))}
        sentiments = {str(item.get("industry") or ""): item for item in self._records(state.get("industry_sentiments"))}
        plans = {str(item.get("stock") or ""): item for item in self._records((state.get("strategy_metadata") or {}).get("trade_plans"))}
        recommendations = {str(stock): rec for rec in self._records((state.get("strategy_metadata") or {}).get("recommendations")) for stock in rec.get("stocks", [])}
        topics = self._records(state.get("guba_topics"))
        stocks = []
        for capital_item in capital:
            industry = str(capital_item.get("industry") or "")
            industry_data = industries.get(industry, {})
            sentiment = sentiments.get(industry, {})
            candidates = list(capital_item.get("top_capital_stocks", []))
            for rank, stock in enumerate(candidates, start=1):
                stock = str(stock)
                quote = quotes.get(stock, {})
                price = self._number(quote.get("current_price"))
                volatility = self._number(quote.get("five_day_volatility"))
                associations = []
                for topic in topics:
                    related = [str(item.get("name") or "") for item in self._records(topic.get("stocks"))]
                    if stock in related or stock in f"{topic.get('title', '')} {topic.get('content', '')}":
                        associations.append({"title": str(topic.get("title") or ""), "url": str(topic.get("url") or ""), "read_count": topic.get("read_count", 0), "comment_count": topic.get("comment_count", 0)})
                plan = plans.get(stock)
                if plan:
                    buy_low, buy_high = plan.get("buy_low"), plan.get("buy_high")
                    stop_price = plan.get("stop_price")
                    target_low, target_high = plan.get("target_low"), plan.get("target_high")
                else:
                    buy_low = round(price * (1 - min(0.025, volatility * 0.35)), 2)
                    buy_high = round(price * 1.005, 2)
                    stop_price = round(buy_low * (1 - min(0.05, max(0.03, volatility * 0.8))), 2)
                    target_low = round(buy_high * (1 + max(0.035, volatility * 0.9)), 2)
                    target_high = round(buy_high * (1 + min(0.10, max(0.06, volatility * 1.8))), 2)
                heat = self._number(industry_data.get("combined_score"))
                sentiment_score = self._number(sentiment.get("sentiment_score"))
                association_score = min(100, len(associations) * 18)
                capital_score = max(45, 100 - (rank - 1) * 18)
                composite = round(heat * 0.5 + capital_score * 0.3 + association_score * 0.2, 1)
                risk_score = round(min(100, volatility * 1000 + max(0, 60 - sentiment_score) * 0.7), 1)
                risk_level = "高" if risk_score >= 55 else "中" if risk_score >= 35 else "低"
                rec = recommendations.get(stock, {})
                selected = bool(plan)
                reasons = list(rec.get("supporting_evidence", [])) if isinstance(rec, Mapping) else []
                if not reasons:
                    reasons = [f"{industry}综合热度 {heat:.0f}", f"行业资金候选排名第 {rank}"]
                    if associations: reasons.append(f"关联 {len(associations)} 条股吧热门话题")
                    if not selected: reasons.append("进入观察池但未进入本次三行业交易组合")
                stocks.append({
                    "stock": stock, "industry": industry, "selected": selected,
                    "association_count": len(associations), "hot_topics": associations[:5],
                    "capital_rank": rank, "current_price": price,
                    "five_day_change_pct": self._number(quote.get("five_day_change_pct")),
                    "volatility_pct": round(volatility * 100, 2), "buy_range": [buy_low, buy_high],
                    "stop_price": stop_price, "target_range": [target_low, target_high],
                    "risk_level": risk_level, "risk_score": risk_score, "composite_score": composite,
                    "industry_heat": heat, "selection_reasons": reasons,
                    "price_plan_type": "交易计划" if selected else "规则观察区间",
                })
        stocks.sort(key=lambda item: (-item["composite_score"], item["risk_score"], item["stock"]))
        return {
            "available": True, "market_data_mode": self.market.data_mode, "stock_count": len(stocks), "stocks": stocks,
            "sort_fields": ["composite_score", "capital_rank", "industry_heat", "risk_score"],
            "message": "当前价格、近5日涨跌和波动率来自可复现模拟行情；话题关联来自真实采集。",
        }

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0)
        except (TypeError, ValueError, OverflowError): return 0.0
