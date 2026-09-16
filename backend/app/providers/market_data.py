"""交易策略使用的行情提供器接口与模拟实现。"""

from __future__ import annotations

import hashlib
import random
from datetime import date
from typing import Any, Mapping, Protocol, Sequence


class MarketDataProvider(Protocol):
    data_mode: str

    async def fetch_quotes(
        self,
        stocks: Sequence[str],
        *,
        as_of_date: str,
    ) -> Mapping[str, Mapping[str, Any]]:
        ...


class SimulatedMarketDataProvider:
    """生成可复现的模拟价格和 5 日波动率，仅供开发演示。"""

    data_mode = "simulated"

    def __init__(self, *, salt: str = "sentra-market-simulation-v1", session_token: str | None = None) -> None:
        self.salt = salt
        self.session_token = session_token or "default"

    async def fetch_quotes(
        self,
        stocks: Sequence[str],
        *,
        as_of_date: str,
    ) -> Mapping[str, Mapping[str, Any]]:
        date.fromisoformat(as_of_date)
        result: dict[str, Mapping[str, Any]] = {}
        for stock in stocks:
            rng = random.Random(self._seed(stock, as_of_date))
            result[stock] = {
                "name": stock,
                # 第三档 27% 仓位也必须能够按 A 股 100 股整手买入。
                "current_price": round(rng.uniform(6.0, 25.0), 2),
                "five_day_volatility": round(rng.uniform(0.018, 0.055), 4),
                "five_day_change_pct": round(rng.uniform(-8.5, 11.5), 2),
                "lot_size": 100,
                "as_of_date": as_of_date,
                "data_mode": self.data_mode,
            }
        return result

    def _seed(self, stock: str, as_of_date: str) -> int:
        raw = f"{self.salt}|{self.session_token}|{stock}|{as_of_date}".encode("utf-8")
        return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
