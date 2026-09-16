"""东方财富股吧热门话题采集节点。

接口属于第三方非稳定接口，因此网络请求和字段标准化被刻意拆开：接口变更时，
只需修改本模块，不会影响后续 Agent 节点使用的标准输出结构。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class GubaCollectionError(RuntimeError):
    """股吧采集失败，且重试次数已经耗尽。"""


@dataclass(frozen=True, slots=True)
class StockReference:
    name: str
    code: str


@dataclass(frozen=True, slots=True)
class GubaTopic:
    title: str
    content: str
    tags: list[str]
    url: str
    read_count: int
    comment_count: int
    favorite_count: int
    stocks: list[StockReference]
    rank: int
    source: str = "eastmoney_guba"
    collected_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EastMoneyGubaCollector:
    """抓取并标准化东方财富股吧热门话题。"""

    GATEWAY_URL = "https://gubatopic.eastmoney.com/interface/GetData.aspx"
    API_PATH = "newtopic/api/Topic/HomePageListRead"
    REFERER = "https://gubatopic.eastmoney.com/"
    TOPIC_URL = "https://gubatopic.eastmoney.com/topic_v3.html?htid={topic_id}"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        timeout: float = 12.0,
        max_retries: int = 3,
        request_interval: float = 0.8,
        cookie: str | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if max_retries < 1:
            raise ValueError("max_retries 必须至少为 1")
        if request_interval < 0:
            raise ValueError("request_interval 不能小于 0")
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_interval = request_interval
        self.cookie = cookie if cookie is not None else os.getenv("EASTMONEY_COOKIE", "")

    def collect(self, *, pages: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
        """同步采集入口，输出可直接序列化的标准 JSON 数据。"""
        if not 1 <= pages <= 20:
            raise ValueError("pages 必须在 1 到 20 之间")
        if not 1 <= page_size <= 50:
            raise ValueError("page_size 必须在 1 到 50 之间")

        topics: list[GubaTopic] = []
        seen: set[tuple[str, str]] = set()
        collected_at = datetime.now(timezone.utc).isoformat()

        for page in range(1, pages + 1):
            payload = self._request_page(page=page, page_size=page_size)
            page_topics = self.parse_payload(
                payload,
                rank_offset=(page - 1) * page_size,
                collected_at=collected_at,
            )
            for topic in page_topics:
                identity = (topic.title, topic.url)
                if identity not in seen:
                    seen.add(identity)
                    topics.append(topic)
            if page < pages and self.request_interval:
                time.sleep(self.request_interval)

        return [topic.to_dict() for topic in topics]

    async def collect_async(
        self, *, pages: int = 1, page_size: int = 50
    ) -> list[dict[str, Any]]:
        """供工作流并行节点调用，避免阻塞事件循环。"""
        return await asyncio.to_thread(self.collect, pages=pages, page_size=page_size)

    def _request_page(self, *, page: int, page_size: int) -> Mapping[str, Any]:
        form = {
            "param": f"ps={page_size}&p={page}&type=0",
            "path": self.API_PATH,
            "env": "2",
        }
        body = urlencode(form).encode("utf-8")
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://gubatopic.eastmoney.com",
            "Referer": self.REFERER,
            "User-Agent": self.USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                request = Request(self.GATEWAY_URL, data=body, headers=headers, method="POST")
                with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    charset = response.headers.get_content_charset() or "utf-8"
                    decoded = response.read().decode(charset, errors="replace")
                    payload = json.loads(decoded)
                    if not isinstance(payload, Mapping):
                        raise ValueError("接口返回的 JSON 顶层不是对象")
                    return payload
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = 0.6 * (2 ** (attempt - 1)) + random.uniform(0.05, 0.25)
                    time.sleep(backoff)

        raise GubaCollectionError(
            f"东方财富股吧第 {page} 页采集失败，已重试 {self.max_retries} 次"
        ) from last_error

    @classmethod
    def parse_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        rank_offset: int = 0,
        collected_at: str = "",
    ) -> list[GubaTopic]:
        """将东方财富原始响应转换成稳定的领域模型。"""
        raw_items = cls._find_items(payload)
        topics: list[GubaTopic] = []
        for index, raw in enumerate(raw_items, start=1):
            if not isinstance(raw, Mapping):
                continue
            topic_id = cls._first_text(raw, "htid", "topicId", "topic_id", "id")
            title = cls._first_text(
                raw, "title", "topicTitle", "topicName", "htName", "name", "nickname"
            )
            content = cls._first_text(raw, "desc", "content", "description", "summary")
            if not title:
                title = content[:40].strip()
            if not title:
                continue

            stocks = cls._extract_stocks(raw)
            tags = list(dict.fromkeys(stock.name for stock in stocks if stock.name))
            explicit_url = cls._first_text(raw, "url", "topicUrl", "link")
            url = explicit_url or (cls.TOPIC_URL.format(topic_id=topic_id) if topic_id else cls.REFERER)

            topics.append(
                GubaTopic(
                    title=title,
                    content=content,
                    tags=tags,
                    url=url,
                    read_count=cls._parse_count(
                        cls._first(raw, "read_count", "readCount", "clickNumber", "viewCount")
                    ),
                    comment_count=cls._parse_count(
                        cls._first(raw, "comment_count", "commentCount", "postNumber", "replyCount")
                    ),
                    favorite_count=cls._parse_count(
                        cls._first(raw, "favorite_count", "favoriteCount", "collectNumber", "followCount")
                    ),
                    stocks=stocks,
                    rank=rank_offset + index,
                    collected_at=collected_at,
                )
            )
        return topics

    @staticmethod
    def _find_items(payload: Mapping[str, Any]) -> list[Any]:
        for key in ("re", "data", "result", "list", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, Mapping):
                nested = EastMoneyGubaCollector._find_items(value)
                if nested:
                    return nested
        return []

    @classmethod
    def _extract_stocks(cls, raw: Mapping[str, Any]) -> list[StockReference]:
        candidates: Any = cls._first(
            raw, "stocks", "stockList", "stock_list", "relatedStocks", "securityList", "tags"
        )
        if isinstance(candidates, str):
            try:
                parsed = json.loads(candidates)
                candidates = parsed if isinstance(parsed, list) else re.split(r"[,，;；|]", candidates)
            except json.JSONDecodeError:
                candidates = re.split(r"[,，;；|]", candidates)

        result: list[StockReference] = []
        if isinstance(candidates, Iterable) and not isinstance(candidates, (str, bytes, Mapping)):
            for candidate in candidates:
                stock = cls._parse_stock(candidate)
                if stock and stock not in result:
                    result.append(stock)

        direct_name = cls._first_text(raw, "stockName", "stock_name", "securityName")
        direct_code = cls._first_text(raw, "stockCode", "stock_code", "securityCode")
        if direct_name or direct_code:
            direct = StockReference(direct_name, cls._normalize_code(direct_code))
            if direct not in result:
                result.append(direct)
        return result

    @classmethod
    def _parse_stock(cls, value: Any) -> StockReference | None:
        if isinstance(value, Mapping):
            name = cls._first_text(value, "name", "stockName", "securityName", "shortName")
            code = cls._first_text(value, "code", "stockCode", "securityCode", "symbol")
            if name or code:
                return StockReference(name=name, code=cls._normalize_code(code))
        elif isinstance(value, str) and value.strip():
            text = value.strip()
            match = re.search(r"(?P<code>\d{6})", text)
            code = match.group("code") if match else ""
            name = re.sub(r"[()（）\[\]]?\d{6}[()（）\[\]]?", "", text).strip(" -—")
            return StockReference(name=name or text, code=code)
        return None

    @staticmethod
    def _normalize_code(value: str) -> str:
        match = re.search(r"\d{6}", value or "")
        return match.group(0) if match else value.strip()

    @staticmethod
    def _parse_count(value: Any) -> int:
        if value is None or value == "":
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return max(0, int(value))
        text = str(value).strip().replace(",", "").replace("+", "")
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return 0
        number = float(match.group(0))
        if "亿" in text:
            number *= 100_000_000
        elif "万" in text or text.lower().endswith("w"):
            number *= 10_000
        return max(0, int(round(number)))

    @staticmethod
    def _first(raw: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            value = raw.get(key)
            if value is not None and value != "":
                return value
        return None

    @classmethod
    def _first_text(cls, raw: Mapping[str, Any], *keys: str) -> str:
        value = cls._first(raw, *keys)
        return "" if value is None else str(value).strip()
