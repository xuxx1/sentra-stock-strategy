from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import URLError

from backend.app.providers.eastmoney_realtime import EastMoneyRealtimeProvider
from backend.app.workflow.market_data_center import MarketDataCenter


class FakeProvider:
    source = "测试数据源"
    methodology = "测试口径"
    calls: list[tuple[str, object]]

    def __init__(self) -> None:
        self.calls = []

    async def fetch_quotes(self, targets=None):
        self.calls.append(("quotes", targets))
        return [{"code": "600000", "name": "浦发银行"}]

    async def fetch_capital_flows(self, targets=None):
        self.calls.append(("capital", targets))
        return [{"code": "600000", "name": "浦发银行"}]


class MarketDataCenterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.provider = FakeProvider()
        self.center = MarketDataCenter(self.provider)  # type: ignore[arg-type]
        self.state = {
            "guba_topics": [{"stocks": [{"name": "浦发银行", "code": "600000"}]}],
            "stock_candidate_pool": {"stocks": [{"stock": "浦发银行"}]},
            "strategy_metadata": {"trade_plans": [{"stock": "浦发银行"}]},
        }

    def test_status_never_fetches_external_data(self) -> None:
        status = self.center.status(self.state)
        self.assertFalse(status["auto_fetch"])
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(status["layers"][1]["target_count"], 1)

    async def test_manual_fetch_uses_selected_scope_and_types(self) -> None:
        result = await self.center.fetch(self.state, "candidates", ["quotes", "capital"])
        self.assertEqual(result["quote_count"], 1)
        self.assertEqual(result["capital_count"], 1)
        self.assertEqual([item[0] for item in self.provider.calls], ["quotes", "capital"])

    async def test_market_scope_does_not_request_detailed_capital_by_default(self) -> None:
        result = await self.center.fetch(self.state, "market", ["quotes"])
        self.assertEqual(result["capital_count"], 0)
        self.assertEqual(self.provider.calls, [("quotes", None)])

    def test_related_pool_has_request_safety_limit(self) -> None:
        state = {"guba_topics": [{"stocks": [{"name": f"股票{i}", "code": str(i)} for i in range(260)]}]}
        status = self.center.status(state)
        self.assertEqual(status["layers"][1]["target_count"], 200)


class EastMoneyRealtimeProviderTests(unittest.TestCase):
    @patch.object(EastMoneyRealtimeProvider, "_request_ipv4")
    @patch("backend.app.providers.eastmoney_realtime.urlopen")
    def test_connection_error_uses_ipv4_fallback(self, mocked_open, mocked_ipv4) -> None:
        mocked_open.side_effect = URLError(OSError(10013, "socket blocked"))
        mocked_ipv4.return_value = {"data": {"diff": [{"f12": "600000", "f14": "浦发银行"}]}}
        rows = EastMoneyRealtimeProvider()._request("f12,f14", "f6")
        self.assertEqual(rows[0]["f12"], "600000")
        mocked_ipv4.assert_called_once()

    @patch.object(EastMoneyRealtimeProvider, "_request_ipv4", side_effect=OSError("blocked"))
    @patch("backend.app.providers.eastmoney_realtime.urlopen", side_effect=URLError(OSError(10013, "blocked")))
    def test_double_connection_failure_is_readable(self, _mocked_open, _mocked_ipv4) -> None:
        with self.assertRaisesRegex(RuntimeError, "无法连接东方财富行情接口"):
            EastMoneyRealtimeProvider()._request("f12,f14", "f6")

    @patch.object(EastMoneyRealtimeProvider, "_request_ipv4", side_effect=OSError("blocked"))
    @patch("backend.app.providers.eastmoney_realtime.urlopen")
    def test_delayed_host_is_last_fallback(self, mocked_open, _mocked_ipv4) -> None:
        response = unittest.mock.MagicMock()
        response.read.return_value = b'{"data":{"diff":[{"f12":"600000"}]}}'
        response.__enter__.return_value = response
        mocked_open.side_effect = [URLError(OSError("blocked")), response]
        rows = EastMoneyRealtimeProvider()._request("f12", "f6")
        self.assertEqual(rows[0]["f12"], "600000")
        delayed_request = mocked_open.call_args_list[1].args[0]
        self.assertIn("push2delay.eastmoney.com", delayed_request.full_url)


if __name__ == "__main__":
    unittest.main()
