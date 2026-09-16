"""东方财富财经经济时评采集节点。"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class FinanceCollectionError(RuntimeError):
    """财经时评页面采集或解析失败。"""


@dataclass(frozen=True, slots=True)
class RankingLink:
    title: str
    url: str
    rank: int


@dataclass(frozen=True, slots=True)
class FinanceCommentary:
    title: str
    time: str
    content: str
    url: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class _RankingParser(HTMLParser):
    """解析 div.tabList ul.h28.fn li a 排行榜链接。"""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.depth = 0
        self.tab_depth: int | None = None
        self.list_depth: int | None = None
        self.li_depth: int | None = None
        self.anchor_depth: int | None = None
        self.anchor_href = ""
        self.anchor_text: list[str] = []
        self.links: list[tuple[str, str]] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key.lower(): value or "" for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attributes = self._attrs(attrs)
        classes = set(attributes.get("class", "").split())
        tag = tag.lower()

        if tag == "div" and "tabList" in classes and self.tab_depth is None:
            self.tab_depth = self.depth
        elif self.tab_depth is not None and tag == "ul" and "h28" in classes:
            # 当前页面通常同时带有 h28 和 fn；只要求 h28 可兼容类名调整。
            self.list_depth = self.depth
        elif self.list_depth is not None and tag == "li":
            self.li_depth = self.depth
        elif self.li_depth is not None and tag == "a" and attributes.get("href"):
            self.anchor_depth = self.depth
            self.anchor_href = attributes["href"].strip()
            self.anchor_text = []

    def handle_data(self, data: str) -> None:
        if self.anchor_depth is not None:
            text = " ".join(data.split())
            if text:
                self.anchor_text.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self.anchor_depth == self.depth:
            title = " ".join(self.anchor_text).strip()
            if title and self.anchor_href:
                self.links.append((title, urljoin(self.base_url, self.anchor_href)))
            self.anchor_depth = None
            self.anchor_href = ""
            self.anchor_text = []
        if tag == "li" and self.li_depth == self.depth:
            self.li_depth = None
        if tag == "ul" and self.list_depth == self.depth:
            self.list_depth = None
        if tag == "div" and self.tab_depth == self.depth:
            self.tab_depth = None
        self.depth = max(0, self.depth - 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


class _ArticleParser(HTMLParser):
    """提取标题、发布时间和 div.contentwrap 正文。"""

    TIME_RE = re.compile(
        r"20\d{2}[年\-/\.]\s*\d{1,2}[月\-/\.]\s*\d{1,2}日?"
        r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"
    )
    BLOCK_TAGS = {"p", "div", "section", "article", "h2", "h3", "li", "br"}
    IGNORED_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.content_depth: int | None = None
        self.title_depth: int | None = None
        self.time_depth: int | None = None
        self.ignored_depths: list[int] = []
        self.content_parts: list[str] = []
        self.title_parts: list[str] = []
        self.time_parts: list[str] = []
        self.meta_title = ""
        self.meta_time = ""

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key.lower(): value or "" for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        tag = tag.lower()
        attributes = self._attrs(attrs)
        classes = set(attributes.get("class", "").split())

        if tag in self.IGNORED_TAGS:
            self.ignored_depths.append(self.depth)
        if tag == "div" and "contentwrap" in classes and self.content_depth is None:
            self.content_depth = self.depth
        if tag == "h1" and self.title_depth is None:
            self.title_depth = self.depth
        if self.time_depth is None and any("time" in name.lower() for name in classes):
            self.time_depth = self.depth
        if tag == "meta":
            marker = (attributes.get("property") or attributes.get("name") or "").lower()
            content = attributes.get("content", "").strip()
            if marker in {"og:title", "twitter:title"} and content:
                self.meta_title = content
            if marker in {"article:published_time", "publishdate", "pubdate"} and content:
                self.meta_time = content
        if self.content_depth is not None and tag in self.BLOCK_TAGS and self.content_parts:
            self.content_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignored_depths:
            return
        clean = " ".join(data.replace("\xa0", " ").split())
        if not clean:
            return
        if self.content_depth is not None:
            self.content_parts.append(clean)
        if self.title_depth is not None:
            self.title_parts.append(clean)
        if self.time_depth is not None:
            self.time_parts.append(clean)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.ignored_depths and self.ignored_depths[-1] == self.depth:
            self.ignored_depths.pop()
        if tag == "h1" and self.title_depth == self.depth:
            self.title_depth = None
        if self.time_depth == self.depth:
            self.time_depth = None
        if tag == "div" and self.content_depth == self.depth:
            self.content_depth = None
        if self.content_depth is not None and tag in self.BLOCK_TAGS and self.content_parts:
            self.content_parts.append("\n")
        self.depth = max(0, self.depth - 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    @property
    def title(self) -> str:
        return self.meta_title or " ".join(self.title_parts).strip()

    @property
    def published_time(self) -> str:
        if self.meta_time:
            return self.meta_time
        text = " ".join(self.time_parts)
        match = self.TIME_RE.search(text)
        return match.group(0).strip() if match else text.strip()

    @property
    def content(self) -> str:
        text = "".join(self.content_parts)
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)


class EastMoneyFinanceCollector:
    """抓取财经频道网友点击排行榜，并访问详情页提取全文。"""

    LIST_URL = "https://finance.eastmoney.com/a/cjjsp.html"
    ALLOWED_HOST_SUFFIX = ".eastmoney.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    )
    TRACKING_QUERY_KEYS = {"from", "spm", "source", "utm_source", "utm_medium", "utm_campaign"}

    def __init__(
        self,
        *,
        timeout: float = 12.0,
        max_retries: int = 3,
        max_workers: int = 4,
        cookie: str | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if max_retries < 1:
            raise ValueError("max_retries 必须至少为 1")
        if not 1 <= max_workers <= 6:
            raise ValueError("max_workers 必须在 1 到 6 之间")
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_workers = max_workers
        self.cookie = cookie if cookie is not None else os.getenv("EASTMONEY_COOKIE", "")

    def collect(
        self,
        *,
        limit: int = 10,
        seen_urls: Iterable[str] | None = None,
    ) -> list[dict[str, str]]:
        """获取排行榜文章全文；已抓取 URL 会在请求详情前被排除。"""
        if not 1 <= limit <= 50:
            raise ValueError("limit 必须在 1 到 50 之间")

        ranking_html = self._request_text(self.LIST_URL, referer="https://finance.eastmoney.com/")
        links = self.parse_ranking_page(ranking_html, limit=limit)
        seen = {self.canonical_url(url) for url in (seen_urls or [])}
        pending = [link for link in links if self.canonical_url(link.url) not in seen]
        if not pending:
            return []

        articles: dict[int, FinanceCommentary] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(pending))) as pool:
            futures = {pool.submit(self._fetch_article, link): link for link in pending}
            for future in as_completed(futures):
                link = futures[future]
                try:
                    articles[link.rank] = future.result()
                except FinanceCollectionError:
                    # 单篇异常不应导致整个排行榜节点失败；监控层可根据数量判断降级。
                    continue
        return [articles[rank].to_dict() for rank in sorted(articles)]

    async def collect_async(
        self,
        *,
        limit: int = 10,
        seen_urls: Iterable[str] | None = None,
    ) -> list[dict[str, str]]:
        return await asyncio.to_thread(self.collect, limit=limit, seen_urls=seen_urls)

    def _fetch_article(self, link: RankingLink) -> FinanceCommentary:
        html = self._request_text(link.url, referer=self.LIST_URL)
        parsed = self.parse_article_page(html, fallback_title=link.title, url=link.url)
        if not parsed.content:
            raise FinanceCollectionError(f"文章正文为空：{link.url}")
        return parsed

    def _request_text(self, url: str, *, referer: str) -> str:
        self._assert_allowed_url(url)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Referer": referer,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.USER_AGENT,
        }
        if self.cookie:
            headers["Cookie"] = self.cookie

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                request = Request(url, headers=headers, method="GET")
                with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    raw = response.read()
                    charset = response.headers.get_content_charset()
                    for encoding in (charset, "utf-8", "gb18030"):
                        if not encoding:
                            continue
                        try:
                            return raw.decode(encoding)
                        except (LookupError, UnicodeDecodeError):
                            continue
                    return raw.decode("utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.6 * (2 ** (attempt - 1)) + random.uniform(0.05, 0.25))
        raise FinanceCollectionError(f"页面访问失败：{url}") from last_error

    @classmethod
    def parse_ranking_page(cls, html: str, *, limit: int = 10) -> list[RankingLink]:
        parser = _RankingParser(cls.LIST_URL)
        parser.feed(html)
        links: list[RankingLink] = []
        seen: set[str] = set()
        for title, raw_url in parser.links:
            try:
                cls._assert_allowed_url(raw_url)
            except ValueError:
                continue
            url = cls.canonical_url(raw_url)
            if url in seen:
                continue
            seen.add(url)
            links.append(RankingLink(title=title, url=url, rank=len(links) + 1))
            if len(links) >= limit:
                break
        return links

    @staticmethod
    def parse_article_page(html: str, *, fallback_title: str, url: str) -> FinanceCommentary:
        parser = _ArticleParser()
        parser.feed(html)
        published_time = parser.published_time
        if not published_time:
            fallback_match = _ArticleParser.TIME_RE.search(html)
            published_time = fallback_match.group(0).strip() if fallback_match else ""
        return FinanceCommentary(
            title=parser.title or fallback_title,
            time=published_time,
            content=parser.content,
            url=EastMoneyFinanceCollector.canonical_url(url),
        )

    @classmethod
    def canonical_url(cls, url: str) -> str:
        split = urlsplit(url.strip())
        clean_query = [
            (key, value)
            for key, value in parse_qsl(split.query, keep_blank_values=True)
            if key.lower() not in cls.TRACKING_QUERY_KEYS
        ]
        return urlunsplit((split.scheme.lower(), split.netloc.lower(), split.path, urlencode(clean_query), ""))

    @classmethod
    def _assert_allowed_url(cls, url: str) -> None:
        split = urlsplit(url)
        host = (split.hostname or "").lower()
        if split.scheme not in {"http", "https"} or not (
            host == "eastmoney.com" or host.endswith(cls.ALLOWED_HOST_SUFFIX)
        ):
            raise ValueError(f"不允许访问非东方财富地址：{url}")
