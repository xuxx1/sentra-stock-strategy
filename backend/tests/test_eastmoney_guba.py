from __future__ import annotations

import unittest

from backend.app.collectors.eastmoney_guba import EastMoneyGubaCollector


class EastMoneyGubaParserTests(unittest.TestCase):
    def test_parses_known_and_fallback_fields(self) -> None:
        payload = {
            "re": [
                {
                    "htid": "11846",
                    "nickname": "AI 算力行情持续发酵",
                    "desc": "市场关注算力基础设施与液冷产业链。",
                    "clickNumber": "12.6万",
                    "postNumber": "1,284",
                    "collectNumber": 306,
                    "stockList": [
                        {"stockName": "中科曙光", "stockCode": "SH603019"},
                        {"name": "浪潮信息", "code": "000977"},
                    ],
                }
            ]
        }

        topics = EastMoneyGubaCollector.parse_payload(payload, collected_at="2026-08-11T00:00:00Z")

        self.assertEqual(len(topics), 1)
        topic = topics[0]
        self.assertEqual(topic.title, "AI 算力行情持续发酵")
        self.assertEqual(topic.read_count, 126_000)
        self.assertEqual(topic.comment_count, 1_284)
        self.assertEqual(topic.favorite_count, 306)
        self.assertEqual(topic.tags, ["中科曙光", "浪潮信息"])
        self.assertEqual(topic.stocks[0].code, "603019")
        self.assertIn("htid=11846", topic.url)

    def test_accepts_nested_items_and_string_stocks(self) -> None:
        payload = {
            "data": {
                "list": [
                    {
                        "topicTitle": "国产替代关注度上升",
                        "description": "半导体设备获得资金关注。",
                        "viewCount": 9000,
                        "replyCount": 87,
                        "stocks": "北方华创(002371), 中微公司(688012)",
                    }
                ]
            }
        }

        topic = EastMoneyGubaCollector.parse_payload(payload, rank_offset=50)[0]

        self.assertEqual(topic.rank, 51)
        self.assertEqual([stock.code for stock in topic.stocks], ["002371", "688012"])
        self.assertEqual(topic.tags, ["北方华创", "中微公司"])

    def test_ignores_records_without_title_or_content(self) -> None:
        topics = EastMoneyGubaCollector.parse_payload({"re": [{"htid": "1"}, "bad"]})
        self.assertEqual(topics, [])

    def test_count_parser_handles_units_and_invalid_values(self) -> None:
        parse = EastMoneyGubaCollector._parse_count
        self.assertEqual(parse("2.3亿"), 230_000_000)
        self.assertEqual(parse("4.5万+"), 45_000)
        self.assertEqual(parse("--"), 0)
        self.assertEqual(parse(-5), 0)


if __name__ == "__main__":
    unittest.main()
