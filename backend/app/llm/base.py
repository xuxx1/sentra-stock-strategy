"""模型供应商无关的最小 LLM 接口。"""

from __future__ import annotations

from typing import Protocol


class LLMClientError(RuntimeError):
    """模型请求或响应失败。"""


class LLMClient(Protocol):
    """所有模型适配器必须实现的异步文本生成协议。"""

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> str:
        """返回模型生成的原始文本。"""
        ...
