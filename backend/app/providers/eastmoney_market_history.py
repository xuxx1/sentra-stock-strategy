"""东方财富日 K 线真实表现查询。"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class EastMoneyMarketHistoryProvider:
    source = "东方财富日K线"
    endpoint = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    async def fetch_after(self, secid: str, after_date: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetch, secid, after_date, limit)

    def _fetch(self, secid: str, after_date: str, limit: int) -> list[dict[str, Any]]:
        date.fromisoformat(after_date)
        query = urlencode({"secid": secid, "klt": 101, "fqt": 1, "lmt": 30, "end": "20500101", "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56"})
        request = Request(f"{self.endpoint}?{query}", headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        klines = ((payload.get("data") or {}).get("klines") or [])
        result = []
        for line in klines:
            fields = str(line).split(",")
            if len(fields) < 6 or fields[0] <= after_date:
                continue
            result.append({"date": fields[0], "open": float(fields[1]), "close": float(fields[2]), "high": float(fields[3]), "low": float(fields[4])})
        return result[:limit]
