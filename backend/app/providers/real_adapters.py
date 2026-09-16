"""真实行情与资金流适配器。

将 EastMoneyRealtimeProvider 采集的全市场数据适配为
MarketDataProvider / ResearchCapitalProvider 协议所需的格式，
使策略工作流可以无缝切换真实与模拟数据源。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.app.providers.research_capital import SimulatedResearchCapitalProvider


class RealMarketDataAdapter:
    """将缓存的东方财富真实行情适配为 MarketDataProvider 协议。"""

    data_mode = "real"

    def __init__(self, quotes: list[Mapping[str, Any]]) -> None:
        # 按股票名称建立索引，方便 O(1) 查找
        self._by_name: dict[str, Mapping[str, Any]] = {}
        for row in quotes:
            name = str(row.get("name") or "").strip()
            if name:
                self._by_name[name] = row

    async def fetch_quotes(
        self,
        stocks: Sequence[str],
        *,
        as_of_date: str,
    ) -> Mapping[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for stock in stocks:
            row = self._by_name.get(stock)
            if row is None:
                continue
            high = _num(row.get("high"))
            low = _num(row.get("low"))
            prev = _num(row.get("previous_close"))
            current = _num(row.get("current_price"))
            # 真实接口没有 5 日波动率，用当日振幅估算
            if high and low and prev and prev > 0:
                volatility = round((high - low) / prev, 4)
            else:
                volatility = 0.03
            result[stock] = {
                "name": stock,
                "current_price": current or 0.0,
                "five_day_volatility": max(0.005, volatility),
                # 真实接口只有当日涨跌幅，用作 5 日近似
                "five_day_change_pct": _num(row.get("change_pct")) or 0.0,
                "lot_size": 100,
                "as_of_date": as_of_date,
                "data_mode": self.data_mode,
                "code": str(row.get("code") or ""),
                "source": "东方财富公开页面接口",
            }
        return result


class RealResearchCapitalAdapter:
    """将缓存的东方财富真实资金流适配为 ResearchCapitalProvider 协议。"""

    data_mode = "real"

    # 内部行业分类到东方财富行业关键词的映射
    INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
        "算力": ("算力", "服务器", "数据中心", "光模块", "光通信"),
        "半导体": ("半导体", "芯片", "集成电路", "存储", "电子"),
        "机器人": ("机器人", "自动化", "智能制造"),
        "新能源车": ("新能源车", "汽车", "电池", "充电"),
        "医药": ("医药", "制药", "医疗", "生物"),
        "能源": ("能源", "石油", "煤炭", "光伏", "储能", "电力"),
        "消费": ("消费", "家电", "食品", "零售", "白酒"),
        "银行": ("银行", "金融"),
        "军工": ("军工", "国防", "航空", "航天"),
    }

    def __init__(self, capital_rows: list[Mapping[str, Any]]) -> None:
        self._rows = capital_rows
        self._by_name: dict[str, Mapping[str, Any]] = {}
        for row in capital_rows:
            name = str(row.get("name") or "").strip()
            if name:
                self._by_name[name] = row

    async def fetch(
        self,
        industries: Sequence[str],
        *,
        as_of_date: str,
    ) -> Mapping[str, Mapping[str, Any]]:
        # 复用模拟 Provider 的股票池做行业→股票映射
        sim = SimulatedResearchCapitalProvider()
        result: dict[str, Mapping[str, Any]] = {}
        for industry in industries:
            universe = sim.STOCK_UNIVERSE.get(industry, ())
            stock_flows: list[dict[str, Any]] = []
            for stock_name in universe:
                row = self._by_name.get(stock_name)
                if row is None:
                    continue
                inflow = _num(row.get("main_net_inflow"))
                if inflow is None:
                    continue
                stock_flows.append({
                    "name": stock_name,
                    "today_net_inflow_million": round(inflow / 1_000_000, 2),
                })
            # 如果按股票池没匹配到，尝试用东方财富行业字段
            if not stock_flows:
                keywords = self.INDUSTRY_KEYWORDS.get(industry, ())
                for row in self._rows:
                    em_industry = str(row.get("industry") or "")
                    if any(kw in em_industry for kw in keywords):
                        name = str(row.get("name") or "").strip()
                        inflow = _num(row.get("main_net_inflow"))
                        if name and inflow is not None:
                            stock_flows.append({
                                "name": name,
                                "today_net_inflow_million": round(inflow / 1_000_000, 2),
                            })
            stock_flows.sort(key=lambda v: -v["today_net_inflow_million"])
            total = sum(v["today_net_inflow_million"] for v in stock_flows) if stock_flows else 0.0
            result[industry] = {
                "data_mode": self.data_mode,
                "as_of_date": as_of_date,
                "research_reports": [],
                # 真实接口只有当日数据，用作单日序列
                "daily_net_inflow_million": [round(total, 2)] if stock_flows else [0.0],
                "stock_capital_flows": stock_flows[:5],
            }
        return result


def _num(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError, OverflowError):
        return None
