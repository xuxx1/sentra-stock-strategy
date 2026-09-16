from __future__ import annotations

import unittest

from backend.app.collectors.eastmoney_finance import EastMoneyFinanceCollector


RANKING_HTML = """
<html><body>
  <div class="tabList">
    <ul class="h28 fn">
      <li><a href="/a/202608111234.html?utm_source=test">政策信号释放新动向</a></li>
      <li><a href="https://finance.eastmoney.com/a/202608115678.html">产业升级打开新空间</a></li>
      <li><a href="/a/202608111234.html">重复文章</a></li>
    </ul>
  </div>
</body></html>
"""

ARTICLE_HTML = """
<html><head>
  <meta property="og:title" content="政策信号释放新动向" />
  <meta property="article:published_time" content="2026-08-11 09:30:00" />
</head><body>
  <div class="contentwrap">
    <p>第一段财经评论内容。</p>
    <p>第二段分析政策对相关行业的影响。</p>
    <script>window.fake = "不应进入正文";</script>
  </div>
</body></html>
"""


class FakeFinanceCollector(EastMoneyFinanceCollector):
    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(max_workers=2)
        self.pages = pages
        self.requested: list[str] = []

    def _request_text(self, url: str, *, referer: str) -> str:
        self.requested.append(url)
        return self.pages[url]


class EastMoneyFinanceTests(unittest.TestCase):
    def test_ranking_selector_and_url_deduplication(self) -> None:
        links = EastMoneyFinanceCollector.parse_ranking_page(RANKING_HTML, limit=10)
        self.assertEqual(len(links), 2)
        self.assertEqual(links[0].title, "政策信号释放新动向")
        self.assertNotIn("utm_source", links[0].url)
        self.assertEqual([link.rank for link in links], [1, 2])

    def test_extracts_complete_content_and_metadata(self) -> None:
        article = EastMoneyFinanceCollector.parse_article_page(
            ARTICLE_HTML,
            fallback_title="排行榜标题",
            url="https://finance.eastmoney.com/a/202608111234.html",
        )
        self.assertEqual(article.title, "政策信号释放新动向")
        self.assertEqual(article.time, "2026-08-11 09:30:00")
        self.assertIn("第一段财经评论内容。", article.content)
        self.assertIn("第二段分析政策对相关行业的影响。", article.content)
        self.assertNotIn("window.fake", article.content)

    def test_seen_url_is_not_requested_again(self) -> None:
        first = "https://finance.eastmoney.com/a/202608111234.html"
        second = "https://finance.eastmoney.com/a/202608115678.html"
        collector = FakeFinanceCollector(
            {
                EastMoneyFinanceCollector.LIST_URL: RANKING_HTML,
                first: ARTICLE_HTML,
                second: ARTICLE_HTML.replace("政策信号释放新动向", "产业升级打开新空间"),
            }
        )

        articles = collector.collect(limit=10, seen_urls=[first + "?utm_source=old"])

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["url"], second)
        self.assertNotIn(first, collector.requested)

    def test_rejects_external_article_links(self) -> None:
        html = '<div class="tabList"><ul class="h28 fn"><li><a href="https://evil.test/a">x</a></li></ul></div>'
        self.assertEqual(EastMoneyFinanceCollector.parse_ranking_page(html), [])


if __name__ == "__main__":
    unittest.main()
