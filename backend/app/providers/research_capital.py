"""研报与资金流数据提供器接口及确定性模拟实现。"""

from __future__ import annotations

import hashlib
import random
from datetime import date
from typing import Any, Mapping, Protocol, Sequence


class ResearchCapitalProvider(Protocol):
    """真实或模拟研报/资金流提供器必须实现的协议。"""

    data_mode: str

    async def fetch(
        self,
        industries: Sequence[str],
        *,
        as_of_date: str,
    ) -> Mapping[str, Mapping[str, Any]]:
        ...


class SimulatedResearchCapitalProvider:
    """按行业和日期生成可复现的模拟数据，仅用于开发与演示。"""

    data_mode = "simulated"
    RATINGS = ("买入", "增持", "中性", "减持")
    STOCK_UNIVERSE = {
        "算力": ("中科曙光", "浪潮信息", "中际旭创"),
        "半导体": ("北方华创", "中微公司", "海光信息"),
        "机器人": ("三花智控", "拓普集团", "绿的谐波"),
        "新能源车": ("比亚迪", "宁德时代", "汇川技术"),
        "消费": ("美的集团", "海尔智家", "伊利股份"),
        "银行": ("招商银行", "工商银行", "宁波银行"),
        "数据中心": ("宝信软件", "光环新网", "数据港"),
        "医药": ("恒瑞医药", "药明康德", "华东医药"),
        "能源": ("中国石油", "中国神华", "阳光电源"),
        "军工": ("中航沈飞", "航发动力", "中航西飞"),
    }

    def __init__(self, *, salt: str = "sentra-simulation-v1", session_token: str | None = None) -> None:
        self.salt = salt
        self.session_token = session_token or "default"

    async def fetch(
        self,
        industries: Sequence[str],
        *,
        as_of_date: str,
    ) -> Mapping[str, Mapping[str, Any]]:
        # 校验日期也能避免同一批模拟数据使用含糊的时间标签。
        date.fromisoformat(as_of_date)
        result: dict[str, Mapping[str, Any]] = {}
        for industry in industries:
            rng = random.Random(self._seed(industry, as_of_date))
            flows = [round(rng.uniform(-180, 220), 2) for _ in range(10)]
            rating = self.RATINGS[rng.randrange(len(self.RATINGS))]
            stock_flows = [
                {"name": name, "today_net_inflow_million": round(rng.uniform(-80, 150), 2)}
                for name in self.STOCK_UNIVERSE.get(industry, ())
            ]
            stock_flows.sort(key=lambda item: (-item["today_net_inflow_million"], item["name"]))
            result[industry] = {
                "data_mode": self.data_mode,
                "as_of_date": as_of_date,
                "research_reports": [
                    {
                        "title": f"{industry}行业模拟跟踪报告",
                        "rating": rating,
                        "summary": f"模拟研报用于验证{industry}行业的数据整合流程，不代表真实机构观点。",
                    }
                ],
                "daily_net_inflow_million": flows,
                "stock_capital_flows": stock_flows,
            }
        return result

    def _seed(self, industry: str, as_of_date: str) -> int:
        payload = f"{self.salt}|{self.session_token}|{industry}|{as_of_date}".encode("utf-8")
        return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
