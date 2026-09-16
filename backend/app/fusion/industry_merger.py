"""模块 3.1：股吧行业与时评行业确定性融合节点。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class CombinedIndustry:
    industry: str
    combined_score: int
    market_hot_score: int
    policy_support_score: int
    combined_logic: str
    hot_topics: list[str]
    policy_signals: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _IndustryEvidence:
    industry: str
    market_ranks: list[int] = field(default_factory=list)
    policy_ranks: list[int] = field(default_factory=list)
    market_logics: list[str] = field(default_factory=list)
    policy_logics: list[str] = field(default_factory=list)
    hot_topics: list[str] = field(default_factory=list)
    policy_signals: list[str] = field(default_factory=list)
    macro_factors: list[str] = field(default_factory=list)


class IndustryFusionNode:
    """将市场关注和政策支持转换为可回放、可解释的综合行业榜单。"""

    DEFAULT_ALIASES = {
        "ai算力": "算力",
        "算力概念": "算力",
        "算力基础设施": "算力",
        "人工智能算力": "算力",
        "芯片": "半导体",
        "芯片概念": "半导体",
        "半导体芯片": "半导体",
        "新能源汽车": "新能源车",
        "新能源汽车产业链": "新能源车",
        "新能源车概念": "新能源车",
        "人形机器人": "机器人",
        "机器人概念": "机器人",
    }

    def __init__(
        self,
        *,
        market_weight: float = 0.55,
        policy_weight: float = 0.45,
        resonance_bonus: int = 8,
        aliases: Mapping[str, str] | None = None,
        max_results: int = 20,
    ) -> None:
        if market_weight < 0 or policy_weight < 0:
            raise ValueError("融合权重不能为负数")
        if abs(market_weight + policy_weight - 1.0) > 1e-9:
            raise ValueError("market_weight 与 policy_weight 之和必须为 1")
        if not 0 <= resonance_bonus <= 30:
            raise ValueError("resonance_bonus 必须在 0 到 30 之间")
        if not 1 <= max_results <= 100:
            raise ValueError("max_results 必须在 1 到 100 之间")
        self.market_weight = market_weight
        self.policy_weight = policy_weight
        self.resonance_bonus = resonance_bonus
        self.max_results = max_results
        alias_source = dict(self.DEFAULT_ALIASES)
        if aliases:
            alias_source.update(aliases)
        self.aliases = {
            self._normalize_industry(source): self._display_name(target)
            for source, target in alias_source.items()
        }

    def merge(
        self,
        guba_industries: Sequence[Mapping[str, Any]],
        commentary_industries: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence: dict[str, _IndustryEvidence] = {}
        self._collect_market_evidence(evidence, guba_industries)
        self._collect_policy_evidence(evidence, commentary_industries)

        combined: list[CombinedIndustry] = []
        for item in evidence.values():
            market_score = self._market_score(item)
            policy_score = self._policy_score(item)
            has_market = bool(item.market_ranks)
            has_policy = bool(item.policy_ranks)
            score = round(
                market_score * self.market_weight
                + policy_score * self.policy_weight
                + (self.resonance_bonus if has_market and has_policy else 0)
            )
            combined.append(
                CombinedIndustry(
                    industry=item.industry,
                    combined_score=min(100, max(0, score)),
                    market_hot_score=market_score,
                    policy_support_score=policy_score,
                    combined_logic=self._combine_logic(item),
                    hot_topics=item.hot_topics,
                    policy_signals=item.policy_signals,
                )
            )

        combined.sort(
            key=lambda item: (
                -item.combined_score,
                -(item.market_hot_score > 0 and item.policy_support_score > 0),
                -item.market_hot_score,
                -item.policy_support_score,
                item.industry,
            )
        )
        return [item.to_dict() for item in combined[: self.max_results]]

    async def run(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """工作流接口：读取两路行业结果，写入 combined_industries。"""
        market = state.get("guba_industries", [])
        policy = state.get("commentary_industries", [])
        if not self._is_record_sequence(market):
            raise ValueError("state.guba_industries 必须是对象列表")
        if not self._is_record_sequence(policy):
            raise ValueError("state.commentary_industries 必须是对象列表")
        return {
            "combined_industries": self.merge(
                [item for item in market if isinstance(item, Mapping)],
                [item for item in policy if isinstance(item, Mapping)],
            )
        }

    def _collect_market_evidence(
        self,
        evidence: dict[str, _IndustryEvidence],
        industries: Sequence[Mapping[str, Any]],
    ) -> None:
        for rank, raw in enumerate(industries, start=1):
            industry = self._text(raw.get("industry"), 50)
            if not industry:
                continue
            key, display = self._identity(industry)
            item = evidence.setdefault(key, _IndustryEvidence(industry=display))
            item.market_ranks.append(rank)
            self._extend_unique(item.market_logics, [self._text(raw.get("logic"), 700)], 4)
            self._extend_unique(item.hot_topics, self._text_list(raw.get("hot_topics"), 20, 160), 20)

    def _collect_policy_evidence(
        self,
        evidence: dict[str, _IndustryEvidence],
        industries: Sequence[Mapping[str, Any]],
    ) -> None:
        for rank, raw in enumerate(industries, start=1):
            industry = self._text(raw.get("industry"), 50)
            if not industry:
                continue
            key, display = self._identity(industry)
            item = evidence.setdefault(key, _IndustryEvidence(industry=display))
            item.policy_ranks.append(rank)
            self._extend_unique(item.policy_logics, [self._text(raw.get("logic"), 700)], 4)
            self._extend_unique(
                item.policy_signals,
                self._text_list(raw.get("policy_signals"), 20, 140),
                20,
            )
            self._extend_unique(
                item.macro_factors,
                self._text_list(raw.get("macro_factors"), 20, 100),
                20,
            )

    @staticmethod
    def _market_score(item: _IndustryEvidence) -> int:
        if not item.market_ranks:
            return 0
        best_rank = min(item.market_ranks)
        rank_score = max(45, 100 - (best_rank - 1) * 7)
        topic_score = min(100, 35 + len(item.hot_topics) * 13)
        repeated_bonus = min(8, (len(item.market_ranks) - 1) * 3)
        return min(100, round(rank_score * 0.72 + topic_score * 0.28 + repeated_bonus))

    @staticmethod
    def _policy_score(item: _IndustryEvidence) -> int:
        if not item.policy_ranks:
            return 0
        best_rank = min(item.policy_ranks)
        rank_score = max(45, 100 - (best_rank - 1) * 7)
        evidence_count = len(item.policy_signals) + min(3, len(item.macro_factors))
        evidence_score = min(100, 35 + evidence_count * 12)
        repeated_bonus = min(8, (len(item.policy_ranks) - 1) * 3)
        return min(100, round(rank_score * 0.72 + evidence_score * 0.28 + repeated_bonus))

    @staticmethod
    def _combine_logic(item: _IndustryEvidence) -> str:
        parts: list[str] = []
        if item.market_logics:
            parts.append("市场侧：" + "；".join(item.market_logics))
        if item.policy_logics:
            parts.append("政策侧：" + "；".join(item.policy_logics))
        if item.market_logics and item.policy_logics:
            parts.append("综合判断：市场关注与政策方向形成共振，持续性仍需资金和基本面验证。")
        elif item.market_logics:
            parts.append("综合判断：当前主要由市场热度驱动，尚缺少明确政策信号验证。")
        elif item.policy_logics:
            parts.append("综合判断：当前主要由政策逻辑驱动，仍需观察市场关注和资金响应。")
        return " ".join(parts)[:1_500]

    def _identity(self, value: str) -> tuple[str, str]:
        normalized = self._normalize_industry(value)
        display = self.aliases.get(normalized, self._display_name(value))
        canonical = self._normalize_industry(display)
        return canonical, display

    @staticmethod
    def _normalize_industry(value: str) -> str:
        text = str(value).strip().lower()
        text = re.sub(r"[\s·•_\-/（）()]+", "", text)
        text = re.sub(r"(?:产业链|行业|板块|概念)$", "", text)
        return text

    @staticmethod
    def _display_name(value: str) -> str:
        text = " ".join(str(value).split()).strip()
        return re.sub(r"(?:产业链|行业|板块|概念)$", "", text) or text

    @staticmethod
    def _extend_unique(target: list[str], values: Iterable[str], limit: int) -> None:
        for value in values:
            if value and value not in target:
                target.append(value)
            if len(target) >= limit:
                break

    @classmethod
    def _text_list(cls, raw: Any, limit: int, max_length: int) -> list[str]:
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, Mapping)):
            return []
        result: list[str] = []
        for item in raw:
            text = cls._text(item, max_length)
            if text and text not in result:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _text(value: Any, max_length: int) -> str:
        if value is None:
            return ""
        return " ".join(str(value).replace("\x00", " ").split())[:max_length].strip()

    @staticmethod
    def _is_record_sequence(value: Any) -> bool:
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes))
