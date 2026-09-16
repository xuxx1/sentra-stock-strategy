"""基于 OpenAI Responses API 的零额外依赖模型适配器。"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import LLMClientError


class OpenAIResponsesClient:
    """使用环境变量配置的 Responses API 客户端。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise LLMClientError("缺少 OPENAI_API_KEY")
        if not model:
            raise LLMClientError("缺少 OPENAI_MODEL")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenAIResponsesClient":
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout=float(os.getenv("OPENAI_TIMEOUT", "120")),
        )

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> str:
        del temperature  # Responses 推理模型由服务端模型配置控制采样。
        return await asyncio.to_thread(
            self._complete_sync,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def _complete_sync(self, *, system_prompt: str, user_prompt: str) -> str:
        endpoint = self.base_url if self.base_url.endswith("/responses") else self.base_url + "/responses"
        body = json.dumps(
            {
                "model": self.model,
                "instructions": system_prompt,
                "input": user_prompt,
                "store": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "sentra-market-intelligence/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise LLMClientError(f"模型接口返回 HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMClientError(f"模型接口调用失败：{exc}") from exc
        text = self.extract_output_text(payload)
        if not text:
            raise LLMClientError("Responses API 未返回文本内容")
        return text

    @staticmethod
    def extract_output_text(payload: Mapping[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        parts: list[str] = []
        output = payload.get("output", [])
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, Mapping) or item.get("type") != "message":
                    continue
                content = item.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, Mapping) and block.get("type") == "output_text":
                        text = block.get("text")
                        if isinstance(text, str) and text.strip():
                            parts.append(text.strip())
        return "\n".join(parts)
