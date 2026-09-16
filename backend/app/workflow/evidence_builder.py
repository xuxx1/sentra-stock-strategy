"""构建策略推荐的可追溯证据链。"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from backend.app.workflow.rule_based import RuleBasedAnalysisEngine


class StrategyEvidenceBuilder:
    """把原始素材、规则计分和策略选择连接成前端可穿透的数据。"""

    def build(self, state: Mapping[str, Any]) -> list[dict[str, Any]]:
        industries = self._records(state.get("combined_industries"))
        sentiments = self._by_industry(state.get("industry_sentiments"))
        capital = self._by_industry(state.get("industry_research_capital"))
        network = state.get("industry_network") if isinstance(state.get("industry_network"), Mapping) else {}
        metadata = state.get("strategy_metadata") if isinstance(state.get("strategy_metadata"), Mapping) else {}
        recommendations = self._recommendations(metadata, industries, capital)
        recommended = {str(item.get("industry")): item for item in recommendations}
        mode = str((state.get("analysis_metadata") or {}).get("mode") or "rule_based")
        topic_evidence = self._topic_evidence(self._records(state.get("guba_topics")))
        article_evidence = self._article_evidence(self._records(state.get("finance_commentary")))
        core = set(network.get("core_industries", []))
        relations = network.get("industry_relations", {}) if isinstance(network.get("industry_relations"), Mapping) else {}

        result: list[dict[str, Any]] = []
        for rank, raw in enumerate(industries, start=1):
            industry = str(raw.get("industry") or "")
            sentiment = sentiments.get(industry, {})
            flow = capital.get(industry, {})
            selection = recommended.get(industry)
            market = self._number(raw.get("market_hot_score"))
            policy = self._number(raw.get("policy_support_score"))
            resonance = 8 if market > 0 and policy > 0 else 0
            stocks = list(selection.get("stocks", [])) if selection else []
            risks = self._text_list(sentiment.get("risk_factors"))
            why = []
            why_not = []
            if selection:
                why = self._text_list(selection.get("supporting_evidence")) or [
                    f"综合榜排名第 {rank}，综合分 {raw.get('combined_score', 0)}",
                    f"情绪分 {sentiment.get('sentiment_score', 0)}",
                    f"资金趋势：{(flow.get('capital_flow') or {}).get('five_days', '待验证')}",
                ]
            else:
                why_not.append(f"综合榜排名第 {rank}，未进入策略默认选择的前三名")
                if not flow.get("top_capital_stocks"):
                    why_not.append("当前没有可校验的资金关注股票候选")
                if self._number(sentiment.get("sentiment_score")) < 62:
                    why_not.append("情绪分未达到规则模式的积极阈值 62")

            position = "核心" if industry in core else self._network_position(industry, relations)
            guba = topic_evidence.get(industry, [])
            finance = article_evidence.get(industry, [])
            result.append({
                "industry": industry,
                "rank": rank,
                "recommended": bool(selection),
                "selected_stocks": stocks,
                "why_recommended": why,
                "why_not_recommended": why_not,
                "scores": {
                    "combined": raw.get("combined_score", 0),
                    "market": raw.get("market_hot_score", 0),
                    "policy": raw.get("policy_support_score", 0),
                    "sentiment": sentiment.get("sentiment_score", 0),
                },
                "score_breakdown": [
                    {"label": "股吧热度", "raw_score": market, "weight": 0.55, "contribution": round(market * 0.55, 2)},
                    {"label": "政策支持", "raw_score": policy, "weight": 0.45, "contribution": round(policy * 0.45, 2)},
                    {"label": "双源共振", "raw_score": resonance, "weight": 1, "contribution": resonance},
                ],
                "guba_evidence": guba,
                "finance_evidence": finance,
                "matched_keywords": sorted({word for item in [*guba, *finance] for word in item["matched_keywords"]}),
                "capital": {
                    "data_mode": str((state.get("research_capital_metadata") or {}).get("data_mode") or "unknown"),
                    "research_rating": flow.get("research_rating", "待接入"),
                    "flow": flow.get("capital_flow", {}),
                    "stocks": flow.get("top_capital_stocks", []),
                },
                "network_position": position,
                "relations": relations.get(industry, {}),
                "risk_factors": risks,
                "rule_calculation": {
                    "formula": "综合分 = 股吧热度×55% + 政策支持×45% + 双源共振8分，最高100分",
                    "sentiment_formula": "情绪分 = 综合分×72% + 核心行业8分（非核心3分） - 风险词扣分",
                    "topic_formula": "单条股吧贡献 = log10(max(10, 阅读数 + 评论数×20)) × 关键词命中系数",
                    "article_formula": "单篇时评贡献 = 行业词命中×3 + 政策词命中×2 + 宏观词命中",
                },
                "model_summary": raw.get("combined_logic") if mode == "openai" else None,
                "mode_comparison": {
                    "available": False,
                    "current_mode": mode,
                    "message": "当前为规则结果，尚无同批次 AI 快照可比较" if mode != "openai" else "当前为 AI 结果；规则审计明细已展示，完整双跑快照尚未生成",
                },
            })
        return result

    def _topic_evidence(self, rows: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for raw in rows:
            title = str(raw.get("title") or "")[:180]
            content = str(raw.get("content") or "")[:1200]
            stocks = [str(item.get("name") or "") for item in self._records(raw.get("stocks"))]
            text = f"{title} {content} {' '.join(stocks)}".lower()
            engagement = math.log10(max(10, self._number(raw.get("read_count")) + self._number(raw.get("comment_count")) * 20))
            for industry, keywords in RuleBasedAnalysisEngine.TAXONOMY:
                hits = [word for word in keywords if word.lower() in text]
                if not hits:
                    continue
                multiplier = 1 + min(2, len(hits) - 1) * 0.2
                result.setdefault(industry, []).append({
                    "title": title, "url": str(raw.get("url") or ""), "matched_keywords": hits,
                    "contribution": round(engagement * multiplier, 2),
                    "read_count": raw.get("read_count", 0), "comment_count": raw.get("comment_count", 0),
                })
        for values in result.values():
            values.sort(key=lambda item: -item["contribution"])
            del values[6:]
        return result

    def _article_evidence(self, rows: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for raw in rows:
            title = str(raw.get("title") or "")[:180]
            text = f"{title} {str(raw.get('content') or '')[:5000]}".lower()
            signals = [word for word in RuleBasedAnalysisEngine.POLICY_WORDS if word in text]
            macros = [word for word in RuleBasedAnalysisEngine.MACRO_WORDS if word in text]
            for industry, keywords in RuleBasedAnalysisEngine.TAXONOMY:
                hits = [word for word in keywords if word.lower() in text]
                if not hits:
                    continue
                result.setdefault(industry, []).append({
                    "title": title, "url": str(raw.get("url") or ""), "time": str(raw.get("time") or ""),
                    "matched_keywords": hits, "policy_keywords": signals, "macro_keywords": macros,
                    "contribution": len(hits) * 3 + len(signals) * 2 + len(macros),
                })
        for values in result.values():
            values.sort(key=lambda item: -item["contribution"])
            del values[5:]
        return result

    @staticmethod
    def _network_position(industry: str, relations: Mapping[str, Any]) -> str:
        for source, value in relations.items():
            if not isinstance(value, Mapping):
                continue
            if industry in value.get("upstream", []): return f"{source}上游"
            if industry in value.get("downstream", []): return f"{source}下游"
            if industry in value.get("related", []): return f"{source}关联"
        return "边缘"

    def _recommendations(self, metadata: Mapping[str, Any], industries: list[Mapping[str, Any]], capital: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        values = self._records(metadata.get("recommendations"))
        if values:
            return values
        return [{"industry": item.get("industry"), "stocks": capital.get(str(item.get("industry")), {}).get("top_capital_stocks", [])[:1]} for item in industries[:3]]

    def _by_industry(self, value: Any) -> dict[str, Mapping[str, Any]]:
        return {str(item.get("industry") or ""): item for item in self._records(value)}

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []

    @staticmethod
    def _text_list(value: Any) -> list[str]:
        return [str(item) for item in value if item] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0)
        except (TypeError, ValueError, OverflowError): return 0.0
