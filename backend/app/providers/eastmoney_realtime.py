"""东方财富公开页面行情与资金流适配器。

本模块不会在导入或页面加载时发起请求；只有业务层显式调用 fetch_* 才访问网络。
公开页面接口没有稳定性承诺，正式生产环境应切换 Choice 等授权数据源。
"""

from __future__ import annotations

import asyncio
import http.client
import json
import socket
import ssl
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode, urlsplit
from urllib.error import URLError
from urllib.request import Request, urlopen


class EastMoneyRealtimeProvider:
    data_mode = "real"
    source = "东方财富公开页面接口（主站/延迟备源）"
    methodology = "东方财富口径"
    endpoint = "https://push2.eastmoney.com/api/qt/clist/get"
    delayed_endpoint = "https://push2delay.eastmoney.com/api/qt/clist/get"
    market_filter = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

    async def fetch_quotes(self, targets: Sequence[Mapping[str, str]] | None = None) -> list[dict[str, Any]]:
        fields = "f12,f14,f2,f3,f5,f6,f8,f15,f16,f17,f18,f100,f124"
        rows = await asyncio.to_thread(self._request, fields, "f6")
        normalized = [self._quote(row) for row in rows]
        return self._filter(normalized, targets)

    async def fetch_capital_flows(self, targets: Sequence[Mapping[str, str]] | None = None) -> list[dict[str, Any]]:
        fields = "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f100,f124"
        rows = await asyncio.to_thread(self._request, fields, "f62")
        normalized = [self._capital(row) for row in rows]
        return self._filter(normalized, targets)

    def _request(self, fields: str, sort_field: str) -> list[Mapping[str, Any]]:
        query = urlencode({
            "pn": 1, "pz": 6000, "po": 1, "np": 1, "fltt": 2, "invt": 2,
            "fid": sort_field, "fs": self.market_filter, "fields": fields,
        })
        request = Request(
            f"{self.endpoint}?{query}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Referer": "https://quote.eastmoney.com/center/gridlist.html",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, OSError) as exc:
            # 部分 Windows 环境会优先选择不可用的 IPv6 路径并返回 WinError 10013。
            # 保留正常请求为首选，仅在连接阶段失败时回退至显式 IPv4 TLS 连接。
            try:
                payload = self._request_ipv4(request.full_url, dict(request.header_items()))
            except Exception:
                delayed_url = request.full_url.replace(self.endpoint, self.delayed_endpoint, 1)
                delayed_request = Request(delayed_url, headers=dict(request.header_items()))
                try:
                    with urlopen(delayed_request, timeout=15) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                except (URLError, OSError) as fallback_exc:
                    raise RuntimeError(
                        "无法连接东方财富行情接口；主站、IPv4和延迟备源均不可用。"
                        "请检查防火墙、代理或安全软件的联网权限。"
                    ) from fallback_exc
        rows = ((payload.get("data") or {}).get("diff") or [])
        if not isinstance(rows, list):
            raise RuntimeError("东方财富返回的数据结构不符合预期")
        return [row for row in rows if isinstance(row, Mapping)]

    @staticmethod
    def _request_ipv4(url: str, headers: Mapping[str, str]) -> Mapping[str, Any]:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        addresses = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        if not addresses:
            raise RuntimeError("东方财富域名没有可用的 IPv4 地址")
        last_error: Exception | None = None
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        for address in dict.fromkeys(item[4][0] for item in addresses):
            connection = http.client.HTTPConnection(address, 443, timeout=15)
            try:
                connection.connect()
                # IP负责建立连接，TLS证书和HTTP Host仍必须使用原始域名。
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=host)
                request_headers = {**headers, "Host": host}
                connection.request("GET", path, headers=request_headers)
                response = connection.getresponse()
                if response.status != 200:
                    raise RuntimeError(f"东方财富返回 HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                last_error = exc
            finally:
                connection.close()
        raise last_error or RuntimeError("IPv4连接失败")

    @classmethod
    def _quote(cls, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "code": str(row.get("f12") or ""), "name": str(row.get("f14") or ""),
            "current_price": cls._number(row.get("f2")), "change_pct": cls._number(row.get("f3")),
            "volume": cls._number(row.get("f5")), "turnover": cls._number(row.get("f6")),
            "turnover_rate": cls._number(row.get("f8")), "high": cls._number(row.get("f15")),
            "low": cls._number(row.get("f16")), "open": cls._number(row.get("f17")),
            "previous_close": cls._number(row.get("f18")), "industry": str(row.get("f100") or ""),
            "quote_timestamp": row.get("f124"), "source": cls.source, "data_mode": cls.data_mode,
        }

    @classmethod
    def _capital(cls, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "code": str(row.get("f12") or ""), "name": str(row.get("f14") or ""),
            "current_price": cls._number(row.get("f2")), "change_pct": cls._number(row.get("f3")),
            "main_net_inflow": cls._number(row.get("f62")), "main_net_inflow_pct": cls._number(row.get("f184")),
            "super_large_net_inflow": cls._number(row.get("f66")), "super_large_net_inflow_pct": cls._number(row.get("f69")),
            "large_net_inflow": cls._number(row.get("f72")), "large_net_inflow_pct": cls._number(row.get("f75")),
            "medium_net_inflow": cls._number(row.get("f78")), "medium_net_inflow_pct": cls._number(row.get("f81")),
            "small_net_inflow": cls._number(row.get("f84")), "small_net_inflow_pct": cls._number(row.get("f87")),
            "industry": str(row.get("f100") or ""), "quote_timestamp": row.get("f124"),
            "source": cls.source, "methodology": cls.methodology, "unit": "元", "data_mode": cls.data_mode,
        }

    @staticmethod
    def _filter(rows: list[dict[str, Any]], targets: Sequence[Mapping[str, str]] | None) -> list[dict[str, Any]]:
        if not targets:
            return rows
        codes = {str(item.get("code") or "").split(".")[0] for item in targets if item.get("code")}
        names = {str(item.get("name") or "") for item in targets if item.get("name")}
        return [row for row in rows if row["code"] in codes or row["name"] in names]

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, "", "-") else None
        except (TypeError, ValueError, OverflowError):
            return None
