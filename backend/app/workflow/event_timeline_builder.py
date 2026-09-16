"""资讯事件分类、影响行业和股票映射。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from backend.app.workflow.rule_based import RuleBasedAnalysisEngine


class EventTimelineBuilder:
    CATEGORIES = (
        ("负面风险", ("风险", "下跌", "减持", "亏损", "处罚", "诉讼", "暴跌", "承压", "下调", "利空")),
        ("公司公告", ("公告", "业绩", "财报", "年报", "季报", "回购", "增持", "中标", "董事会", "股东")),
        ("海外市场", ("美股", "纳斯达克", "道琼斯", "标普", "欧洲", "日本", "海外", "美联储", "美元", "英伟达")),
        ("政策", ("政策", "国务院", "央行", "发改委", "工信部", "财政部", "证监会", "降息", "降准", "补贴", "规划")),
        ("宏观事件", ("通胀", "利率", "汇率", "经济增长", "GDP", "PMI", "出口", "进口", "流动性", "就业")),
    )

    def build(self, state: Mapping[str, Any], *, limit: int = 30) -> dict[str, Any]:
        candidates = self._stock_industries(state)
        events = []
        for article in self._records(state.get("finance_commentary")):
            events.append(self._event(article, "东方财富财经", candidates, default_category="行业新闻"))
        for topic in self._records(state.get("guba_topics"))[:15]:
            events.append(self._event(topic, "东方财富股吧", candidates, default_category="行业新闻"))
        events = [item for item in events if item["title"]]
        events.sort(key=lambda item: item["timestamp"], reverse=True)
        counts: dict[str, int] = {name: 0 for name, _ in self.CATEGORIES}
        counts["行业新闻"] = 0
        for item in events: counts[item["category"]] = counts.get(item["category"], 0) + 1
        return {
            "available": bool(events), "events": events[:limit], "category_counts": counts,
            "categories": ["政策", "公司公告", "行业新闻", "宏观事件", "海外市场", "负面风险"],
            "message": "事件分类来自确定性关键词规则；影响行业来自行业词典，影响股票来自原始关联和当前候选池。",
        }

    def _event(self, raw: Mapping[str, Any], source: str, candidates: Mapping[str, str], *, default_category: str) -> dict[str, Any]:
        title = str(raw.get("title") or "").strip()[:180]
        content = str(raw.get("content") or "")[:5000]
        text = f"{title} {content}".lower()
        category = default_category
        matched_category_words: list[str] = []
        for name, keywords in self.CATEGORIES:
            hits = [word for word in keywords if word.lower() in text]
            if hits:
                category, matched_category_words = name, hits
                break
        industries = []
        matched_industry_words: list[str] = []
        for industry, keywords in RuleBasedAnalysisEngine.TAXONOMY:
            hits = [word for word in keywords if word.lower() in text]
            if hits:
                industries.append(industry)
                matched_industry_words.extend(hits)
        direct_stocks = [str(item.get("name") or "") for item in self._records(raw.get("stocks")) if item.get("name")]
        stocks = list(dict.fromkeys([*direct_stocks, *[stock for stock, industry in candidates.items() if stock in text or industry in industries]]))[:10]
        timestamp = str(raw.get("time") or raw.get("collected_at") or datetime.now(timezone.utc).isoformat())
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp = (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).isoformat()
        except ValueError:
            timestamp = datetime.now(timezone.utc).isoformat()
        return {
            "id": f"{source}:{raw.get('url') or title}", "title": title, "summary": content[:220],
            "timestamp": timestamp, "category": category, "source": source, "url": str(raw.get("url") or ""),
            "affected_industries": industries, "affected_stocks": stocks,
            "matched_keywords": list(dict.fromkeys([*matched_category_words, *matched_industry_words]))[:12],
            "impact_level": "high" if category == "负面风险" or len(industries) >= 3 else "medium" if industries or stocks else "low",
        }

    def _stock_industries(self, state: Mapping[str, Any]) -> dict[str, str]:
        pool = state.get("stock_candidate_pool") if isinstance(state.get("stock_candidate_pool"), Mapping) else {}
        return {str(item.get("stock") or ""): str(item.get("industry") or "") for item in self._records(pool.get("stocks"))}

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []
