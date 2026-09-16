"""从真实采集到策略报告的完整工作流服务。"""

from __future__ import annotations

import asyncio
import copy
import os
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo
from pathlib import Path

from backend.app.agents import (
    FinanceIndustryAnalysisAgent,
    GubaIndustryAnalysisAgent,
    IndustryNetworkAgent,
    IndustrySentimentAgent,
    ResearchCapitalAgent,
    TradingStrategyAgent,
)
from backend.app.collectors import EastMoneyFinanceCollector, EastMoneyGubaCollector
from backend.app.fusion import IndustryFusionNode
from backend.app.llm import OpenAIResponsesClient
from backend.app.providers import SimulatedMarketDataProvider, SimulatedResearchCapitalProvider
from backend.app.providers.eastmoney_market_history import EastMoneyMarketHistoryProvider
from backend.app.providers.real_adapters import RealMarketDataAdapter, RealResearchCapitalAdapter
from backend.app.workflow.rule_based import RuleBasedAnalysisEngine
from backend.app.workflow.evidence_builder import StrategyEvidenceBuilder
from backend.app.workflow.risk_control import RiskControlBuilder
from backend.app.workflow.history_store import StrategyHistoryStore
from backend.app.workflow.burst_store import SentimentBurstStore
from backend.app.workflow.quadrant_builder import IndustryQuadrantBuilder
from backend.app.workflow.divergence_builder import SentimentCapitalDivergenceBuilder
from backend.app.workflow.stock_pool_builder import StockCandidatePoolBuilder
from backend.app.workflow.event_timeline_builder import EventTimelineBuilder
from backend.app.workflow.execution_board_builder import StrategyExecutionBoardBuilder
from backend.app.workflow.market_data_center import MarketDataCenter
from backend.app.workflow.persistence_store import WorkflowPersistenceStore
from backend.app.workflow.trend_store import TrendSnapshotStore


class WorkflowError(RuntimeError):
    """工作流缺少前置数据或执行失败。"""


class PipelineService:
    """在单进程内保存最近一次采集与分析结果。"""

    def __init__(self, *, trend_db_path: str | Path | None = None) -> None:
        data_dir = Path(trend_db_path).parent if trend_db_path else Path(__file__).resolve().parents[2] / "data"
        self.persistence = WorkflowPersistenceStore(data_dir / "sentra.sqlite3")
        default_state: dict[str, Any] = {
            "stage": "idle",
            "updated_at": "",
            "analysis_date": date.today().isoformat(),
            "analysis_engine": "auto",  # auto | rule | llm
            "source_stats": {
                "guba": {"attempts": 0, "successes": 0, "last_failure": ""},
                "finance": {"attempts": 0, "successes": 0, "last_failure": ""},
            },
            "workflow_nodes": self._empty_workflow_nodes(),
        }
        restored = self.persistence.load_state()
        self._state = {**default_state, **(restored or {})}
        self._state["workflow_nodes"] = self._normalize_restored_nodes(self._state.get("workflow_nodes"))
        self._state_lock = threading.RLock()
        self.run_lock = threading.Lock()
        self.scheduler: Any | None = None
        self.trend_store = TrendSnapshotStore(
            trend_db_path or Path(__file__).resolve().parents[2] / "data" / "industry_trends.sqlite3"
        )
        history_path = Path(trend_db_path).with_name("strategy_history.sqlite3") if trend_db_path else Path(__file__).resolve().parents[2] / "data" / "strategy_history.sqlite3"
        self.history_store = StrategyHistoryStore(history_path)
        burst_path = Path(trend_db_path).with_name("sentiment_bursts.sqlite3") if trend_db_path else Path(__file__).resolve().parents[2] / "data" / "sentiment_bursts.sqlite3"
        self.burst_store = SentimentBurstStore(burst_path)
        self.market_data_center = MarketDataCenter()

    def attach_scheduler(self, scheduler: Any) -> None:
        self.scheduler = scheduler

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return copy.deepcopy(self._state)

    def _update(self, **values: Any) -> None:
        with self._state_lock:
            self._state.update(values)
            self._state["updated_at"] = datetime.now(timezone.utc).isoformat()
            snapshot = copy.deepcopy(self._state)
        self.persistence.save_state(snapshot)

    async def collect(
        self,
        target_type: str | None = None,
        target_name: str | None = None,
        period: str | None = None,
    ) -> dict[str, Any]:
        self._apply_research_focus(target_type=target_type, target_name=target_name, period=period)
        self._update(stage="collecting", last_error="")
        guba = EastMoneyGubaCollector()
        finance = EastMoneyFinanceCollector()
        snapshot = self.snapshot()
        stats = copy.deepcopy(snapshot.get("source_stats", {}))
        for key in ("guba", "finance"):
            stats.setdefault(key, {"attempts": 0, "successes": 0, "last_failure": ""})
            stats[key]["attempts"] += 1
        guba_result, finance_result = await asyncio.gather(
            self._execute_node(
                "guba_collect", "crawler", 1,
                lambda: guba.collect_async(pages=1, page_size=50),
                "guba_topics",
            ),
            self._execute_node(
                "finance_collect", "crawler", 1,
                lambda: finance.collect_async(limit=10),
                "finance_commentary",
            ),
            return_exceptions=True,
        )
        errors: list[str] = []
        if isinstance(guba_result, Exception):
            stats["guba"]["last_failure"] = str(guba_result)
            errors.append(f"股吧：{guba_result}")
            guba_topics = snapshot.get("guba_topics", [])
        else:
            stats["guba"]["successes"] += 1
            guba_topics = guba_result["guba_topics"]
        if isinstance(finance_result, Exception):
            stats["finance"]["last_failure"] = str(finance_result)
            errors.append(f"财经时评：{finance_result}")
            finance_commentary = snapshot.get("finance_commentary", [])
        else:
            stats["finance"]["successes"] += 1
            finance_commentary = finance_result["finance_commentary"]
        if errors:
            message = "；".join(errors)
            self._update(
                stage="error",
                last_error=message,
                source_stats=stats,
                guba_topics=guba_topics,
                finance_commentary=finance_commentary,
            )
            raise WorkflowError(f"数据采集失败：{message}")
        collected_at = datetime.now(timezone.utc).isoformat()
        burst_snapshot_id = self.burst_store.save(guba_topics, finance_commentary, captured_at=collected_at)
        collection_summary = {
            "guba_topic_count": len(guba_topics), "finance_article_count": len(finance_commentary),
            "collected_at": collected_at, "burst_snapshot_id": burst_snapshot_id,
        }
        collection_batch_id = self.persistence.save_collection(guba_topics, finance_commentary, collection_summary)
        self._update(
            stage="collected",
            guba_topics=guba_topics,
            finance_commentary=finance_commentary,
            collection_summary=collection_summary,
            collection_batch_id=collection_batch_id,
            source_stats=stats,
        )
        return self.public_result()

    async def incremental_news_check(self) -> dict[str, Any]:
        """Fetch only unseen finance articles and analyze only important events."""
        snapshot = self.snapshot()
        existing = self._records(snapshot.get("finance_commentary"))
        existing_urls = {str(item.get("url") or "") for item in existing if item.get("url")}
        stats = copy.deepcopy(snapshot.get("source_stats", {}))
        stats.setdefault("finance", {"attempts": 0, "successes": 0, "last_failure": ""})
        stats["finance"]["attempts"] += 1
        try:
            fresh = await EastMoneyFinanceCollector(max_workers=2).collect_async(limit=10, seen_urls=existing_urls)
            stats["finance"]["successes"] += 1
        except Exception as exc:
            stats["finance"]["last_failure"] = str(exc)
            self._update(source_stats=stats)
            raise WorkflowError(f"重要新闻增量检查失败：{exc}") from exc
        if not fresh:
            self._update(source_stats=stats)
            return {"new_articles": 0, "important_articles": 0, "analysis_triggered": False,
                    "message": "没有发现新的排行榜文章"}

        important_words = (
            "政策", "国务院", "央行", "发改委", "工信部", "财政部", "证监会", "降息", "降准", "补贴", "规划",
            "风险", "处罚", "减持", "亏损", "暴跌", "下调", "利空", "回购", "增持", "中标", "业绩",
            "美联储", "利率", "汇率", "通胀", "GDP", "PMI",
        )
        important = [item for item in fresh if any(word.lower() in f"{item.get('title', '')} {item.get('content', '')}".lower() for word in important_words)]
        merged_by_url = {str(item.get("url") or ""): item for item in [*fresh, *existing] if item.get("url")}
        merged = list(merged_by_url.values())[:50]
        collected_at = datetime.now(timezone.utc).isoformat()
        summary = {
            "guba_topic_count": len(self._records(snapshot.get("guba_topics"))),
            "finance_article_count": len(merged),
            "incremental_article_count": len(fresh),
            "important_article_count": len(important),
            "collection_type": "incremental_news",
            "collected_at": collected_at,
        }
        batch_id = self.persistence.save_collection([], fresh, summary)
        self._update(finance_commentary=merged, collection_summary=summary,
                     collection_batch_id=batch_id, source_stats=stats)
        if important and snapshot.get("guba_topics"):
            await self.analyze()
        return {"new_articles": len(fresh), "important_articles": len(important),
                "analysis_triggered": bool(important and snapshot.get("guba_topics")),
                "titles": [str(item.get("title") or "") for item in important[:5]]}

    def set_analysis_engine(self, engine: str) -> dict[str, Any]:
        """切换分析引擎：auto（有 Key 用 LLM、无 Key 用规则）| rule（强制纯规则）| llm（强制大模型）。"""
        if engine not in ("auto", "rule", "llm"):
            raise WorkflowError("分析引擎只能是 auto、rule 或 llm")
        if engine == "llm" and not os.getenv("OPENAI_API_KEY"):
            raise WorkflowError("尚未配置 OPENAI_API_KEY，无法切换到大模型模式")
        self._update(analysis_engine=engine)
        return {
            "analysis_engine": engine,
            "model_configured": bool(os.getenv("OPENAI_API_KEY")),
            "effective_mode": self._effective_mode(engine),
        }

    def _effective_mode(self, engine: str | None = None) -> str:
        """返回当前引擎选择下的实际分析模式：openai 或 rule_based。"""
        configured = bool(os.getenv("OPENAI_API_KEY"))
        chosen = engine or self.snapshot().get("analysis_engine", "auto")
        if chosen == "rule":
            return "rule_based"
        if chosen == "llm":
            return "openai" if configured else "rule_based"
        return "openai" if configured else "rule_based"

    async def analyze(
        self,
        target_type: str | None = None,
        target_name: str | None = None,
        period: str | None = None,
        analysis_engine: str | None = None,
        market_data_mode: str | None = None,
    ) -> dict[str, Any]:
        state = self.snapshot()
        if not state.get("guba_topics") or not state.get("finance_commentary"):
            raise WorkflowError("尚无采集数据，请先点击“采集数据”或运行全链路")
        self._apply_research_focus(
            target_type=target_type,
            target_name=target_name,
            period=period,
            analysis_engine=analysis_engine,
            market_data_mode=market_data_mode,
        )
        state = self.snapshot()
        # 每次研判生成新的 session_token：模拟数据 provider 会基于它重新随机化资金流和行情，
        # 让用户连续点击"开始研判"能看到不同的候选股票、价格区间与回测结果。
        state["session_token"] = uuid.uuid4().hex[:10]
        state["analysis_started_at"] = datetime.now(timezone.utc).isoformat()
        self._update(**{"session_token": state["session_token"], "analysis_started_at": state["analysis_started_at"]})
        self._update(stage="analyzing", last_error="")
        try:
            fallback_reasons: list[str] = []
            for node_id in ("industry_analysis", "industry_fusion", "industry_network", "sentiment_analysis", "capital_integration", "strategy_report"):
                update, fallback_reason = await self._run_analysis_node(node_id, state)
                state.update(update)
                self._update(**update)
                if fallback_reason:
                    fallback_reasons.append(f"{self.NODE_LABELS[node_id]}：{fallback_reason}")
            configured = bool(os.getenv("OPENAI_API_KEY")) and state.get("analysis_engine", "auto") in ("auto", "llm")
            state["analysis_metadata"] = {
                "mode": "rule_based_fallback" if fallback_reasons and configured else "openai" if configured else "rule_based",
                "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna") if configured else "",
                "fallback_used": not configured or bool(fallback_reasons),
                "fallback_reason": "；".join(fallback_reasons) if fallback_reasons else ("未配置 OPENAI_API_KEY" if not configured else ""),
            }
            state["strategy_evidence"] = StrategyEvidenceBuilder().build(state)
            real_market = state.get("real_market_quotes")
            use_real = bool(real_market) and state.get("market_data_mode") == "real"
            session_token_local = str(state.get("session_token") or uuid.uuid4().hex[:10])
            pool_provider = RealMarketDataAdapter(real_market) if use_real else SimulatedMarketDataProvider(session_token=session_token_local)
            state["stock_candidate_pool"] = await StockCandidatePoolBuilder(market_provider=pool_provider).build(state)
        except Exception as exc:
            self._update(stage="error", last_error=str(exc))
            raise WorkflowError(f"分析工作流失败：{exc}") from exc
        state["stage"] = "complete"
        state["analysis_completed_at"] = datetime.now(timezone.utc).isoformat()
        state["trading_strategy"] = self._compose_trading_strategy(state.get("trading_strategy", ""), state.get("research_focus"))
        state["workflow_nodes"] = self.snapshot().get("workflow_nodes", self._empty_workflow_nodes())
        state["trend_snapshot_id"] = self.trend_store.save(
            self._records(state.get("combined_industries")),
            self._records(state.get("industry_sentiments")),
            analysis_mode=str(state.get("analysis_metadata", {}).get("mode") or "unknown"),
            captured_at=state["analysis_completed_at"],
        )
        state["strategy_archive_id"] = self.history_store.archive(state)
        state["analysis_archive_id"] = self.persistence.save_analysis(state)
        self._update(**state)
        return self.public_result()

    @staticmethod
    def _compose_trading_strategy(report: str, focus: Mapping[str, Any] | None) -> str:
        """把研判焦点行插到策略报告顶部，让"输入行业名称"肉眼可见地影响结果。"""
        if not focus:
            return report
        target_type = str(focus.get("target_type") or "").strip()
        target_name = str(focus.get("target_name") or "").strip()
        period = str(focus.get("period") or "").strip()
        if not (target_name or period or target_type):
            return report
        type_label = {"industry": "行业", "stock": "股票", "pool": "股票池"}.get(target_type, target_type or "对象")
        parts: list[str] = []
        if target_name:
            parts.append(f"目标 {type_label}：{target_name}")
        if period:
            parts.append(f"策略周期：{period} 日")
        if not parts:
            return report
        header_line = "【本次研判焦点】" + "｜".join(parts) + "（系统将围绕该目标生成综合判断与 5 日策略）"
        report = str(report or "")
        if report.startswith("【本次研判焦点】"):
            return report
        return f"{header_line}\n\n{report}" if report else header_line

    NODE_LABELS = {
        "guba_collect": "股吧采集",
        "finance_collect": "财经采集",
        "industry_analysis": "行业分析",
        "industry_fusion": "行业融合",
        "industry_network": "关联网络",
        "sentiment_analysis": "情绪分析",
        "capital_integration": "资金整合",
        "strategy_report": "策略报告",
    }

    NODE_OUTPUT_KEYS = {
        "guba_collect": ("guba_topics",),
        "finance_collect": ("finance_commentary",),
        "industry_analysis": ("guba_industries", "commentary_industries"),
        "industry_fusion": ("combined_industries",),
        "industry_network": ("industry_network",),
        "sentiment_analysis": ("industry_sentiments",),
        "capital_integration": ("industry_research_capital", "research_capital_metadata"),
        "strategy_report": ("trading_strategy", "strategy_metadata"),
    }

    @classmethod
    def _empty_workflow_nodes(cls) -> dict[str, dict[str, Any]]:
        return {
            node_id: {
                "id": node_id,
                "name": label,
                "status": "waiting",
                "started_at": "",
                "ended_at": "",
                "duration_ms": None,
                "input_count": 0,
                "output_count": 0,
                "mode": "",
                "retry_count": 0,
                "run_count": 0,
                "error": "",
                "output": {},
            }
            for node_id, label in cls.NODE_LABELS.items()
        }

    @classmethod
    def _normalize_restored_nodes(cls, value: Any) -> dict[str, dict[str, Any]]:
        defaults = cls._empty_workflow_nodes()
        if not isinstance(value, Mapping):
            return defaults
        for node_id, node in value.items():
            if node_id not in defaults or not isinstance(node, Mapping):
                continue
            restored = {**defaults[node_id], **dict(node)}
            if restored.get("status") == "running":
                restored.update({"status": "failed", "ended_at": datetime.now(timezone.utc).isoformat(), "error": "服务重启时节点仍在运行，已标记为中断"})
            defaults[node_id] = restored
        return defaults

    async def _execute_node(
        self,
        node_id: str,
        mode: str,
        input_count: int,
        action: Any,
        output_key: str | None = None,
    ) -> dict[str, Any]:
        nodes = copy.deepcopy(self.snapshot().get("workflow_nodes") or self._empty_workflow_nodes())
        previous = nodes.get(node_id, self._empty_workflow_nodes()[node_id])
        started = datetime.now(timezone.utc)
        previous.update({
            "status": "running",
            "started_at": started.isoformat(),
            "ended_at": "",
            "duration_ms": None,
            "input_count": input_count,
            "output_count": 0,
            "mode": mode,
            "retry_count": int(previous.get("retry_count") or 0) + (1 if previous.get("status") == "failed" else 0),
            "run_count": int(previous.get("run_count") or 0) + 1,
            "error": "",
            "output": {},
        })
        nodes[node_id] = previous
        self._update(workflow_nodes=nodes)
        try:
            raw = await action()
            update = {output_key: raw} if output_key else dict(raw)
        except Exception as exc:
            self._finish_node(node_id, started, "failed", {}, str(exc))
            raise
        self._finish_node(node_id, started, "success", update, "")
        return update

    def _finish_node(
        self, node_id: str, started: datetime, status: str, update: Mapping[str, Any], error: str
    ) -> None:
        ended = datetime.now(timezone.utc)
        nodes = copy.deepcopy(self.snapshot().get("workflow_nodes") or self._empty_workflow_nodes())
        node = nodes[node_id]
        node.update({
            "status": status,
            "ended_at": ended.isoformat(),
            "duration_ms": round((ended - started).total_seconds() * 1000),
            "output_count": self._output_count(update),
            "error": error[:1_000],
            "output": self._output_preview(update),
        })
        nodes[node_id] = node
        self._update(workflow_nodes=nodes)
        self.persistence.save_node_log(node)

    async def _run_analysis_node(
        self, node_id: str, state: Mapping[str, Any]
    ) -> tuple[dict[str, Any], str]:
        self._validate_node_prerequisites(node_id, state)
        engine = str(state.get("analysis_engine") or "auto")
        configured = bool(os.getenv("OPENAI_API_KEY")) and engine in ("auto", "llm")
        real_market = state.get("real_market_quotes")
        real_capital = state.get("real_capital_flows")
        use_real_market = bool(real_market) and state.get("market_data_mode") == "real"
        use_real_capital = bool(real_capital) and state.get("market_data_mode") == "real"
        # 模拟数据按每次"研判运行"重新随机化；真实数据与本次 token 无关。
        session_token = str(state.get("session_token") or uuid.uuid4().hex[:10])
        market_provider = RealMarketDataAdapter(real_market) if use_real_market else SimulatedMarketDataProvider(session_token=session_token)
        research_provider = RealResearchCapitalAdapter(real_capital) if use_real_capital else SimulatedResearchCapitalProvider(session_token=session_token)
        rule_engine = RuleBasedAnalysisEngine(research_provider=research_provider, market_provider=market_provider)
        llm = OpenAIResponsesClient.from_env() if configured and node_id != "industry_fusion" else None
        mode = "deterministic" if node_id == "industry_fusion" else "openai" if configured else "rule_based"
        input_count = self._node_input_count(node_id, state)

        async def execute(prefer_llm: bool) -> dict[str, Any]:
            if node_id == "industry_analysis":
                if prefer_llm and llm:
                    market, policy = await asyncio.gather(
                        GubaIndustryAnalysisAgent(llm).run(state), FinanceIndustryAnalysisAgent(llm).run(state)
                    )
                    return {**market, **policy}
                return {
                    "guba_industries": rule_engine.analyze_topics(self._records(state.get("guba_topics"))),
                    "commentary_industries": rule_engine.analyze_commentary(self._records(state.get("finance_commentary"))),
                }
            if node_id == "industry_fusion":
                return await IndustryFusionNode().run(state)
            if node_id == "industry_network":
                return await IndustryNetworkAgent(llm).run(state) if prefer_llm and llm else {"industry_network": rule_engine.build_network(self._records(state.get("combined_industries")))}
            if node_id == "sentiment_analysis":
                return await IndustrySentimentAgent(llm).run(state) if prefer_llm and llm else {
                    "industry_sentiments": rule_engine.analyze_sentiment(
                        self._records(state.get("combined_industries")),
                        state.get("industry_network", {}),
                        self._records(state.get("guba_topics")),
                        self._records(state.get("finance_commentary")),
                    )
                }
            if node_id == "capital_integration":
                if prefer_llm and llm:
                    return await ResearchCapitalAgent(llm, research_provider).run(state)
                values, metadata = await rule_engine.integrate_research_capital(
                    self._records(state.get("industry_sentiments")), str(state.get("analysis_date") or "")
                )
                return {"industry_research_capital": values, "research_capital_metadata": metadata}
            if node_id == "strategy_report":
                if prefer_llm and llm:
                    return await TradingStrategyAgent(llm, market_provider).run(state)
                return await rule_engine.generate_strategy(
                    self._records(state.get("combined_industries")),
                    state.get("industry_network", {}),
                    self._records(state.get("industry_sentiments")),
                    self._records(state.get("industry_research_capital")),
                    state.get("research_capital_metadata", {}),
                    str(state.get("analysis_date") or ""),
                )
            raise WorkflowError(f"未知节点：{node_id}")

        try:
            update = await self._execute_node(node_id, mode, input_count, lambda: execute(configured))
            return update, ""
        except Exception as model_error:
            if not configured or node_id == "industry_fusion":
                raise
            update = await self._execute_node(node_id, "rule_based_fallback", input_count, lambda: execute(False))
            return update, str(model_error)[:500]

    async def run_node(self, node_id: str) -> dict[str, Any]:
        if node_id not in self.NODE_LABELS:
            raise WorkflowError("节点不存在")
        if node_id in {"guba_collect", "finance_collect"}:
            collector = EastMoneyGubaCollector() if node_id == "guba_collect" else EastMoneyFinanceCollector()
            action = (lambda: collector.collect_async(pages=1, page_size=50)) if node_id == "guba_collect" else (lambda: collector.collect_async(limit=10))
            update = await self._execute_node(node_id, "crawler", 1, action, self.NODE_OUTPUT_KEYS[node_id][0])
            self._update(stage="collected", last_error="", **update)
        else:
            state = self.snapshot()
            update, fallback_reason = await self._run_analysis_node(node_id, state)
            values: dict[str, Any] = {**update, "last_error": ""}
            if node_id == "strategy_report":
                values["stage"] = "complete"
                values["analysis_completed_at"] = datetime.now(timezone.utc).isoformat()
            self._update(**values)
            if fallback_reason:
                metadata = dict(self.snapshot().get("analysis_metadata", {}))
                metadata.update({"mode": "rule_based_fallback", "fallback_used": True, "fallback_reason": fallback_reason})
                self._update(analysis_metadata=metadata)
            if node_id == "strategy_report":
                refreshed = self.snapshot()
                self._update(strategy_evidence=StrategyEvidenceBuilder().build(refreshed))
                refreshed = self.snapshot()
                real_market = refreshed.get("real_market_quotes")
                use_real = bool(real_market) and refreshed.get("market_data_mode") == "real"
                pool_provider = RealMarketDataAdapter(real_market) if use_real else SimulatedMarketDataProvider()
                self._update(stock_candidate_pool=await StockCandidatePoolBuilder(market_provider=pool_provider).build(refreshed))
                archived = self.snapshot()
                self._update(strategy_archive_id=self.history_store.archive(archived))
        return self.public_result()

    def _validate_node_prerequisites(self, node_id: str, state: Mapping[str, Any]) -> None:
        requirements = {
            "industry_analysis": ("guba_topics", "finance_commentary"),
            "industry_fusion": ("guba_industries", "commentary_industries"),
            "industry_network": ("combined_industries",),
            "sentiment_analysis": ("combined_industries", "industry_network"),
            "capital_integration": ("industry_sentiments",),
            "strategy_report": ("combined_industries", "industry_network", "industry_sentiments", "industry_research_capital"),
        }
        missing = [key for key in requirements.get(node_id, ()) if not state.get(key)]
        if missing:
            raise WorkflowError(f"{self.NODE_LABELS[node_id]}缺少前置数据：{'、'.join(missing)}")

    def _node_input_count(self, node_id: str, state: Mapping[str, Any]) -> int:
        keys = {
            "industry_analysis": ("guba_topics", "finance_commentary"),
            "industry_fusion": ("guba_industries", "commentary_industries"),
            "industry_network": ("combined_industries",),
            "sentiment_analysis": ("combined_industries",),
            "capital_integration": ("industry_sentiments",),
            "strategy_report": ("combined_industries", "industry_research_capital"),
        }.get(node_id, ())
        return sum(len(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else 1 for key in keys if (value := state.get(key)))

    @staticmethod
    def _output_count(update: Mapping[str, Any]) -> int:
        count = 0
        for value in update.values():
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                count += len(value)
            elif value:
                count += 1
        return count

    @staticmethod
    def _output_preview(update: Mapping[str, Any]) -> dict[str, Any]:
        preview: dict[str, Any] = {}
        for key, value in update.items():
            if isinstance(value, list):
                preview[key] = value[:5]
            elif isinstance(value, str):
                preview[key] = value[:3_000]
            else:
                preview[key] = value
        return preview

    async def run_full(
        self,
        target_type: str | None = None,
        target_name: str | None = None,
        period: str | None = None,
        analysis_engine: str | None = None,
        market_data_mode: str | None = None,
    ) -> dict[str, Any]:
        await self.collect(target_type=target_type, target_name=target_name, period=period)
        return await self.analyze(
            target_type=target_type,
            target_name=target_name,
            period=period,
            analysis_engine=analysis_engine,
            market_data_mode=market_data_mode,
        )

    def _apply_research_focus(
        self,
        *,
        target_type: str | None = None,
        target_name: str | None = None,
        period: str | None = None,
        analysis_engine: str | None = None,
        market_data_mode: str | None = None,
    ) -> None:
        """把本次提交的研判焦点写进 state，前端可直接读取；空值不覆盖已有值。"""
        focus = dict(self.snapshot().get("research_focus") or {})
        if target_type:
            focus["target_type"] = str(target_type).strip()
        if target_name:
            focus["target_name"] = str(target_name).strip()
        if period:
            focus["period"] = str(period).strip()
        # engine / market_mode 仅在显式传入时记录（不强制覆盖手动切换）
        if analysis_engine in (None, ""):
            analysis_engine = None
        if market_data_mode in (None, ""):
            market_data_mode = None
        if focus and (focus.get("target_name") or focus.get("period")):
            focus["submitted_at"] = datetime.now(timezone.utc).isoformat()
            self._update(research_focus=focus)
        # 显式传入的 mode/engine 必须真正写回 state，否则后端会一直沿用持久化层里的旧值，
        # 导致"点开始研判"看起来没反应（数据完全不变）。
        if analysis_engine in ("rule", "llm", "auto"):
            self._update(analysis_engine=analysis_engine)
        if market_data_mode in ("simulated", "real"):
            self._update(market_data_mode=market_data_mode)

    async def apply_real_data(self) -> dict[str, Any]:
        """用已缓存的真实行情+资金流重新运行策略层（capital_integration → strategy_report）。"""
        snapshot = self.snapshot()
        if not snapshot.get("real_market_quotes") and not snapshot.get("real_capital_flows"):
            raise WorkflowError("尚未获取真实行情或资金流数据，请先点击「获取行情+资金流」")
        self._update(market_data_mode="real", last_error="")
        state = self.snapshot()
        for node_id in ("capital_integration", "strategy_report"):
            update, fallback_reason = await self._run_analysis_node(node_id, state)
            state.update(update)
            self._update(**update)
        # 重建证据链和候选池
        refreshed = self.snapshot()
        real_market = refreshed.get("real_market_quotes")
        pool_provider = RealMarketDataAdapter(real_market) if real_market else SimulatedMarketDataProvider(session_token=str(refreshed.get("session_token") or uuid.uuid4().hex[:10]))
        self._update(
            strategy_evidence=StrategyEvidenceBuilder().build(refreshed),
            stock_candidate_pool=await StockCandidatePoolBuilder(market_provider=pool_provider).build(refreshed),
            stage="complete",
            analysis_completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return self.public_result()

    async def reset_to_simulated(self) -> dict[str, Any]:
        """切回模拟数据模式并重新生成策略。"""
        self._update(market_data_mode="simulated", last_error="")
        state = self.snapshot()
        for node_id in ("capital_integration", "strategy_report"):
            update, _ = await self._run_analysis_node(node_id, state)
            state.update(update)
            self._update(**update)
        refreshed = self.snapshot()
        self._update(
            strategy_evidence=StrategyEvidenceBuilder().build(refreshed),
            stock_candidate_pool=await StockCandidatePoolBuilder().build(refreshed),
            stage="complete",
            analysis_completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return self.public_result()

    async def refresh_history(self) -> dict[str, Any]:
        provider = EastMoneyMarketHistoryProvider()
        pending = self.history_store.pending_positions()
        for item in pending:
            if not item.get("stock_code"):
                self.history_store.save_observation(int(item["id"]), [], source=provider.source, error="缺少股票代码映射")
                continue
            try:
                bars = await provider.fetch_after(str(item["stock_code"]), str(item["analysis_date"]), limit=5)
                self.history_store.save_observation(int(item["id"]), bars, source=provider.source)
            except Exception as exc:
                self.history_store.save_observation(int(item["id"]), [], source=provider.source, error=str(exc)[:300])
        return self.public_result()

    def public_result(self) -> dict[str, Any]:
        state = self.snapshot()
        trends = self.trend_store.build_trends(limit=5, hours=24)
        trust = self._build_data_trust(state)
        burst = self.burst_store.radar(hours=1, limit=8)
        quadrant = IndustryQuadrantBuilder().build(state)
        return {
            "stage": state.get("stage", "idle"),
            "updated_at": state.get("updated_at", ""),
            "last_error": state.get("last_error", ""),
            "analysis_date": state.get("analysis_date"),
            "collection_summary": state.get("collection_summary", {}),
            "guba_topics": state.get("guba_topics", []),
            "finance_commentary": state.get("finance_commentary", []),
            "combined_industries": state.get("combined_industries", []),
            "industry_network": state.get("industry_network", {}),
            "industry_sentiments": state.get("industry_sentiments", []),
            "industry_research_capital": state.get("industry_research_capital", []),
            "research_capital_metadata": state.get("research_capital_metadata", {}),
            "trading_strategy": state.get("trading_strategy", ""),
            "strategy_metadata": state.get("strategy_metadata", {}),
            "research_focus": state.get("research_focus") or {},
            "session_token": state.get("session_token"),
            "analysis_started_at": state.get("analysis_started_at"),
            "strategy_evidence": state.get("strategy_evidence", []),
            "stock_candidate_pool": state.get("stock_candidate_pool", {"available": False, "stocks": []}),
            "analysis_metadata": state.get("analysis_metadata", {}),
            "analysis_engine": state.get("analysis_engine", "auto"),
            "effective_mode": self._effective_mode(state.get("analysis_engine")),
            "market_data_mode": state.get("market_data_mode", "simulated"),
            "market_data_center_status": self.market_data_center.status(state),
            "workflow_nodes": list((state.get("workflow_nodes") or self._empty_workflow_nodes()).values()),
            "industry_trends": trends,
            "data_trust": trust,
            "risk_control": RiskControlBuilder().build(state, trust, trends),
            "strategy_history": self.history_store.summary(limit=30),
            "strategy_archive_id": state.get("strategy_archive_id"),
            "persistence_status": self.persistence.status(),
            "scheduler_status": self.scheduler.status() if self.scheduler else {
                "enabled": False, "running": False, "jobs": [], "recent_runs": [],
                "calendar_note": "调度器仅在 API 服务进程中启动。",
            },
            "sentiment_burst_radar": burst,
            "industry_quadrant": quadrant,
            "sentiment_capital_divergence": SentimentCapitalDivergenceBuilder().build(state, trends, burst, quadrant),
            "event_timeline": EventTimelineBuilder().build(state, limit=30),
            "strategy_execution": StrategyExecutionBoardBuilder().build(state),
        }

    def admin_result(self) -> dict[str, Any]:
        state = self.snapshot()
        public = self.public_result()
        return {
            "updated_at": public.get("updated_at"),
            "stage": public.get("stage"),
            "last_error": public.get("last_error"),
            "data_trust": public.get("data_trust"),
            "persistence_status": public.get("persistence_status"),
            "scheduler_status": public.get("scheduler_status"),
            "workflow_nodes": public.get("workflow_nodes"),
            "collection_summary": public.get("collection_summary"),
            "guba_topics": self._records(state.get("guba_topics"))[:50],
            "finance_commentary": self._records(state.get("finance_commentary"))[:50],
            "market_data_center": {
                **self.market_data_center.status(state),
                "workflow_mode": str(state.get("market_data_mode") or "simulated"),
            },
            **self.persistence.admin_overview(limit=30),
        }

    async def fetch_market_data(self, scope: str, data_types: Sequence[str]) -> dict[str, Any]:
        result = await self.market_data_center.fetch(self.snapshot(), scope, data_types)
        updates: dict[str, Any] = {"market_data_center_last_run": result}
        # 将完整真实数据写入 state 缓存，供「应用到策略」使用；此处不切换 market_data_mode，
        # 保持两步流程：先获取缓存，再显式应用到策略层。
        if result.get("data_mode") == "real":
            all_quotes = list(result.get("quotes", []))
            all_capital = list(result.get("capital", []))
            if all_quotes:
                updates["real_market_quotes"] = all_quotes
            if all_capital:
                updates["real_capital_flows"] = all_capital
        self._update(**updates)
        return result

    def _build_data_trust(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """构建前端可直接展示、并会随时间更新的新鲜度指标。"""
        topics = self._records(state.get("guba_topics"))
        articles = self._records(state.get("finance_commentary"))
        collection = state.get("collection_summary", {})
        collection = collection if isinstance(collection, Mapping) else {}
        collected_at = str(collection.get("collected_at") or "")
        analysis_at = str(state.get("analysis_completed_at") or "")
        stats = state.get("source_stats", {})
        stats = stats if isinstance(stats, Mapping) else {}

        has_real_market = bool(state.get("real_market_quotes")) and state.get("market_data_mode") == "real"
        has_real_capital = bool(state.get("real_capital_flows")) and state.get("market_data_mode") == "real"
        market_row = (
            self._real_source_row(
                key="market", name="个股行情", source="东方财富公开页面接口",
                records=self._records(state.get("real_market_quotes")),
                required=("name", "current_price"),
                expected=50,
                updated_at=str(state.get("market_data_center_last_run", {}).get("completed_at", "")) if isinstance(state.get("market_data_center_last_run"), Mapping) else "",
                stats={},
            )
            if has_real_market
            else self._simulated_source_row("market", "个股行情", "确定性模拟行情提供器", analysis_at, bool(state.get("trading_strategy")))
        )
        capital_row = (
            self._real_source_row(
                key="capital", name="主力资金流", source="东方财富公开页面接口",
                records=self._records(state.get("real_capital_flows")),
                required=("name", "main_net_inflow"),
                expected=50,
                updated_at=str(state.get("market_data_center_last_run", {}).get("completed_at", "")) if isinstance(state.get("market_data_center_last_run"), Mapping) else "",
                stats={},
            )
            if has_real_capital
            else self._simulated_source_row("capital", "主力资金流", "确定性模拟资金流提供器", analysis_at, bool(state.get("industry_research_capital")))
        )
        rows = [
            self._real_source_row(
                key="guba",
                name="股吧热门话题",
                source="东方财富股吧",
                records=topics,
                required=("title", "url", "read_count", "comment_count"),
                expected=50,
                updated_at=collected_at,
                stats=stats.get("guba", {}),
            ),
            self._real_source_row(
                key="finance",
                name="财经时评",
                source="东方财富财经点击榜",
                records=articles,
                required=("title", "time", "content", "url"),
                expected=10,
                updated_at=collected_at,
                stats=stats.get("finance", {}),
                publication_lag_minutes=self._publication_lag(articles, collected_at),
            ),
            self._simulated_source_row("research", "行业研报", "确定性模拟研报提供器", analysis_at, bool(state.get("industry_research_capital"))),
            capital_row,
            market_row,
        ]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall_level": self._overall_trust_level(rows),
            "sources": rows,
        }

    def _real_source_row(
        self,
        *,
        key: str,
        name: str,
        source: str,
        records: Sequence[Mapping[str, Any]],
        required: Sequence[str],
        expected: int,
        updated_at: str,
        stats: Any,
        publication_lag_minutes: float | None = None,
    ) -> dict[str, Any]:
        stats = stats if isinstance(stats, Mapping) else {}
        attempts = int(stats.get("attempts") or 0)
        successes = int(stats.get("successes") or 0)
        field_total = len(records) * len(required)
        missing = sum(
            not self._has_value(record.get(field))
            for record in records
            for field in required
        )
        missing_rate = round(missing / field_total * 100, 1) if field_total else 100.0
        success_rate = round(successes / attempts * 100, 1) if attempts else 0.0
        completeness_rate = round(min(100, len(records) / expected * 100), 1)
        freshness, age_minutes = self._freshness(updated_at, fresh_minutes=60, warning_minutes=240)
        return {
            "key": key,
            "name": name,
            "mode": "real",
            "source": source,
            "updated_at": updated_at,
            "record_count": len(records),
            "expected_count": expected,
            "success_rate": success_rate,
            "completeness_rate": completeness_rate,
            "missing_rate": missing_rate,
            "last_failure": str(stats.get("last_failure") or ""),
            "freshness": freshness,
            "age_minutes": age_minutes,
            "publication_lag_minutes": publication_lag_minutes,
        }

    def _simulated_source_row(
        self, key: str, name: str, source: str, updated_at: str, available: bool
    ) -> dict[str, Any]:
        freshness, age_minutes = self._freshness(updated_at, fresh_minutes=240, warning_minutes=1_440)
        return {
            "key": key,
            "name": name,
            "mode": "simulated",
            "source": source,
            "updated_at": updated_at,
            "record_count": None,
            "expected_count": None,
            "success_rate": None,
            "completeness_rate": 100.0 if available else 0.0,
            "missing_rate": 0.0 if available else 100.0,
            "last_failure": "",
            "freshness": freshness if available else "not_run",
            "age_minutes": age_minutes if available else None,
            "publication_lag_minutes": None,
        }

    @staticmethod
    def _records(value: Any) -> list[Mapping[str, Any]]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return []
        return [item for item in value if isinstance(item, Mapping)]

    @staticmethod
    def _has_value(value: Any) -> bool:
        return value is not None and value != "" and value != [] and value != {}

    @staticmethod
    def _freshness(value: str, *, fresh_minutes: int, warning_minutes: int) -> tuple[str, float | None]:
        if not value:
            return "not_run", None
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age = max(0.0, (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() / 60)
        except ValueError:
            return "unknown", None
        level = "fresh" if age <= fresh_minutes else "warning" if age <= warning_minutes else "stale"
        return level, round(age, 1)

    @staticmethod
    def _publication_lag(articles: Sequence[Mapping[str, Any]], collected_at: str) -> float | None:
        if not collected_at:
            return None
        try:
            collected = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
            collected = collected.astimezone(ZoneInfo("Asia/Shanghai"))
        except ValueError:
            return None
        lags: list[float] = []
        for article in articles:
            raw = str(article.get("time") or "").strip()
            parsed: datetime | None = None
            for pattern in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y年%m月%d日 %H:%M"):
                try:
                    parsed = datetime.strptime(raw, pattern).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                    break
                except ValueError:
                    continue
            if parsed is not None:
                lags.append(max(0.0, (collected - parsed).total_seconds() / 60))
        return round(sum(lags) / len(lags), 1) if lags else None

    @staticmethod
    def _overall_trust_level(rows: Sequence[Mapping[str, Any]]) -> str:
        real_rows = [row for row in rows if row.get("mode") == "real"]
        if not real_rows or any(row.get("freshness") in {"stale", "not_run", "unknown"} for row in real_rows):
            return "warning"
        if any(float(row.get("missing_rate") or 0) > 10 or float(row.get("success_rate") or 0) < 90 for row in real_rows):
            return "warning"
        return "good"
