"""按需行情与资金数据中心：只在用户手动触发时访问外部数据源。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from backend.app.providers.eastmoney_realtime import EastMoneyRealtimeProvider


class MarketDataCenter:
    VALID_SCOPES = ("market", "related", "candidates", "recommended")
    VALID_TYPES = ("quotes", "capital")

    def __init__(self, provider: EastMoneyRealtimeProvider | None = None) -> None:
        self.provider = provider or EastMoneyRealtimeProvider()

    def status(self, state: Mapping[str, Any]) -> dict[str, Any]:
        targets = self._targets(state)
        # 同时统计"原始话题关联条目数"与"过滤掉无效 code 后的有效目标数"，方便后台看清
        # 为什么舆情关联池拿到的数据量远小于话题里出现的标的数。
        raw_related = self._raw_related(state)
        definitions = {
            "market": ("全市场轻量扫描", "全A股", "最新价、涨跌幅、成交额、换手率和行业", "建议30分钟"),
            "related": ("舆情关联池", f"{len(targets['related'])}只", "股吧与资讯直接关联股票的行情和资金流", "每轮分析"),
            "candidates": ("策略候选池", f"{len(targets['candidates'])}只", "候选股票行情、主力资金和风险计算输入", "建议5–15分钟"),
            "recommended": ("最终推荐池", f"{len(targets['recommended'])}只", "最终标的执行状态与资金变化", "建议1–5分钟"),
        }
        layers = []
        for scope in self.VALID_SCOPES:
            name, count_label, description, frequency = definitions[scope]
            mapped = sum(self._is_valid_a_share_code(item.get("code")) for item in targets[scope])
            layer = {
                "scope": scope, "name": name, "count_label": count_label, "target_count": len(targets[scope]),
                "mapped_count": mapped, "description": description, "frequency": frequency,
                "default_types": ["quotes"] if scope == "market" else ["quotes", "capital"],
            }
            if scope == "related":
                # 让后台一眼看出"原始话题标的 vs 有效 A 股目标"的差距
                layer["raw_related_count"] = len(raw_related)
                layer["filtered_count"] = len(raw_related) - len(targets[scope])
            layers.append(layer)
        return {
            "provider": self.provider.source, "provider_type": "public_web_api", "auto_fetch": False,
            "data_mode": "real_on_demand", "methodology": self.provider.methodology,
            "warning": "页面加载不会抓取；只有点击获取按钮才访问东方财富。公开页面接口仅用于研究验证。",
            "layers": layers, "last_run": state.get("market_data_center_last_run"),
        }

    async def fetch(self, state: Mapping[str, Any], scope: str, data_types: Sequence[str]) -> dict[str, Any]:
        if scope not in self.VALID_SCOPES:
            raise ValueError("不支持的采集范围")
        kinds = list(dict.fromkeys(str(item) for item in data_types))
        if not kinds or any(item not in self.VALID_TYPES for item in kinds):
            raise ValueError("数据类型只能是 quotes 或 capital")
        targets = None if scope == "market" else self._targets(state)[scope]
        started_at = datetime.now(timezone.utc)
        quote_rows = await self.provider.fetch_quotes(targets) if "quotes" in kinds else []
        capital_rows = await self.provider.fetch_capital_flows(targets) if "capital" in kinds else []
        completed_at = datetime.now(timezone.utc)
        return {
            "scope": scope, "data_types": kinds, "status": "success", "source": self.provider.source,
            "methodology": self.provider.methodology, "data_mode": "real", "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(), "duration_ms": round((completed_at - started_at).total_seconds() * 1000),
            "target_count": "all" if targets is None else len(targets), "quote_count": len(quote_rows),
            "capital_count": len(capital_rows),
            # 全量数据供策略工作流使用，样本仅用于展示
            "quotes": quote_rows, "capital": capital_rows,
            "quotes_sample": quote_rows[:20], "capital_sample": capital_rows[:20],
            "note": "已缓存全量行情与资金流；点击「应用到策略」后才会替换策略工作流中的模拟 Provider。",
        }

    @classmethod
    def _targets(cls, state: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
        identity: dict[str, dict[str, str]] = {}
        for topic in cls._records(state.get("guba_topics")):
            for stock in cls._records(topic.get("stocks")):
                name = str(stock.get("name") or "").strip()
                code = str(stock.get("code") or "").strip()
                if name:
                    identity[name] = {"name": name, "code": code}
        # related 在去重前只保留"code 是 A 股 6 位数字"的条目，避免指数 / 海外品种 /
        # 拼音代号等不可在东方财富行情接口匹配的项污染池子（否则按 targets 数去拿数据，
        # 永远只能拿到极少数，反而让用户误以为接口失灵）。
        related_all = [item for item in identity.values() if cls._is_valid_a_share_code(item.get("code"))]
        related = related_all
        pool = cls._records((state.get("stock_candidate_pool") or {}).get("stocks"))
        candidates = [identity.get(str(item.get("stock") or ""), {"name": str(item.get("stock") or ""), "code": ""}) for item in pool if item.get("stock")]
        plans = cls._records((state.get("strategy_metadata") or {}).get("trade_plans"))
        recommended = [identity.get(str(item.get("stock") or ""), {"name": str(item.get("stock") or ""), "code": str(item.get("stock_code") or "")}) for item in plans if item.get("stock")]
        # 手动按钮也采用安全上限，避免一次请求把异常庞大的话题关联集合全部送入详细处理。
        # 注：东方财富 /api/qt/clist/get 公开接口单次最多返回约 100 行（按 f62 / f6 排序），
        # 因此 related 池不能超过接口返回上限，否则命中率会大幅下降（~30%）。
        return {
            "market": [], "related": cls._unique(related)[:80],
            "candidates": cls._unique(candidates)[:50], "recommended": cls._unique(recommended)[:6],
        }

    @classmethod
    def _raw_related(cls, state: Mapping[str, Any]) -> list[dict[str, str]]:
        """汇总 guba_topics 中所有出现的标的（不去重、不限 code 格式），用于状态对比。"""
        items: list[dict[str, str]] = []
        for topic in cls._records(state.get("guba_topics")):
            for stock in cls._records(topic.get("stocks")):
                name = str(stock.get("name") or "").strip()
                code = str(stock.get("code") or "").strip()
                if name:
                    items.append({"name": name, "code": code})
        return items

    @staticmethod
    def _is_valid_a_share_code(code: Any) -> bool:
        """只接受沪深 A 股 6 位数字代码，避免拼音代号（如 zsgjudi）或港股 / 美股被错认为标的。

        同时剔除常见的指数 / ETF 代码——东方财富沪深 A 股行情接口本身不返回指数行情，
        若不剔除就会让 targets 看起来很多，实际只能匹配到 20%~30% 的命中率。"""
        text = str(code or "").strip()
        if len(text) != 6 or not text.isdigit():
            return False
        return text not in _INDEX_LIKE_CODES

    @staticmethod
    def _unique(items: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in items:
            key = str(item.get("code") or item.get("name") or "")
            if key and key not in seen:
                seen.add(key); result.append({"name": str(item.get("name") or ""), "code": str(item.get("code") or "")})
        return result

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


# 已被东方财富沪深个股接口排除的"指数 / ETF / 中证系列 / 国证系列"代码。
# 这里只列举股吧话题中常见出现、又不属于可交易个股的代码。
_INDEX_LIKE_CODES: frozenset[str] = frozenset({
    "000001", "000002", "000003", "000004", "000005",  # 上证指数系列
    "000300", "000905", "000852",  # 沪深 300 / 中证 500 / 中证 1000
    "399001", "399002", "399003", "399004", "399005", "399006",
    "399100", "399101", "399106", "399107", "399108", "399300",
    "399371", "399372", "399373", "399400", "399401", "399905",
    "399986", "399987", "399989", "399996", "399997", "399998",
})
