"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

export type Topic = { title: string; content?: string; read_count?: number; comment_count?: number; rank?: number; stocks?: { name: string; code: string }[] };
export type Article = { title: string; time: string; content?: string; url: string };
export type Industry = { industry: string; combined_score: number; market_hot_score: number; policy_support_score: number; combined_logic: string; hot_topics: string[]; policy_signals: string[] };
export type Sentiment = { industry: string; sentiment: "positive" | "neutral" | "negative"; sentiment_score: number; sentiment_drivers: string[]; risk_factors: string[] };
export type Capital = { industry: string; research_rating: string; capital_flow: { today: string; five_days: string; ten_days: string }; top_capital_stocks: string[] };
export type Network = { core_industries?: string[]; industry_relations?: Record<string, { upstream: string[]; downstream: string[]; related: string[] }>; analysis?: string };
export type TrustSource = { key: string; name: string; mode: "real" | "simulated"; source: string; updated_at?: string; record_count?: number | null; expected_count?: number | null; success_rate?: number | null; completeness_rate: number; missing_rate: number; last_failure?: string; freshness: "fresh" | "warning" | "stale" | "not_run" | "unknown"; age_minutes?: number | null; publication_lag_minutes?: number | null };
export type WorkflowNode = { id: string; name: string; status: "waiting" | "running" | "success" | "failed"; started_at?: string; ended_at?: string; duration_ms?: number | null; input_count: number; output_count: number; mode?: string; retry_count: number; run_count: number; error?: string; output?: Record<string, unknown> };
export type TrendPoint = { captured_at: string; rank: number; combined_score: number; market_hot_score: number; policy_support_score: number; sentiment_score: number };
export type IndustryTrend = { industry: string; current_rank: number; current_score: number; score_change_24h: number; rank_change_24h: number; rank_history: number[]; tags: string[]; persistence_hours: number; points: TrendPoint[] };
export type EvidenceItem = { title: string; url: string; time?: string; matched_keywords: string[]; policy_keywords?: string[]; macro_keywords?: string[]; contribution: number; read_count?: number; comment_count?: number };
export type StrategyEvidence = { industry: string; rank: number; recommended: boolean; selected_stocks: string[]; why_recommended: string[]; why_not_recommended: string[]; scores: { combined: number; market: number; policy: number; sentiment: number }; score_breakdown: { label: string; raw_score: number; weight: number; contribution: number }[]; guba_evidence: EvidenceItem[]; finance_evidence: EvidenceItem[]; matched_keywords: string[]; capital: { data_mode: string; research_rating: string; flow: { today?: string; five_days?: string; ten_days?: string }; stocks: string[] }; network_position: string; relations: { upstream?: string[]; downstream?: string[]; related?: string[] }; risk_factors: string[]; rule_calculation: Record<string, string>; model_summary?: string | null; mode_comparison: { available: boolean; current_mode: string; message: string } };
export type RiskControl = { available: boolean; message?: string; total_capital?: number; invested_amount?: number; remaining_cash?: number; max_stock_position_pct?: number; max_industry_position_pct?: number; concentration_index?: number; concentration_level?: string; expected_return_pct?: number; max_risk_pct?: number; max_risk_amount?: number; reward_risk_ratio?: number | null; negative_news_count?: number; stock_risks?: { stock: string; industry: string; position_amount: number; position_pct: number; stop_price: number; estimated_stop_loss: number }[]; industry_positions?: { industry: string; amount: number; position_pct: number }[]; alerts?: { level: string; type: string; message: string }[]; scenarios?: { name: string; result_pct: number; result_amount: number; advice: string }[]; calculation_note?: string };
export type StrategyHistory = { archived_count: number; verified_5d_count: number; pending_count: number; simulation_only_count: number; win_rate: number | null; average_5d_return: number | null; average_max_drawdown: number | null; profit_loss_ratio: number | null; industry_performance: { industry: string; samples: number; average_return: number; win_rate: number }[]; mode_comparison: { mode: string; verified_count: number; win_rate: number | null; average_return: number | null }[]; excess_return: { available: boolean; value?: number | null; message: string }; recent_strategies: { id: number; generated_at: string; analysis_mode: string; market_data_mode: string; status: string; industries: string[]; stocks: string[]; verified_days: number }[]; failure_cases: { run_id: number; generated_at: string; return_pct: number; reason: string }[]; methodology: string };
export type BurstItem = { type: string; name: string; industry: string; discussion_delta_1h: number | null; read_growth_rate: number | null; comment_growth_rate: number | null; news_growth_rate: number | null; source: string; first_seen_at: string; burst_score: number; is_new: boolean };
export type BurstRadar = { ready: boolean; sample_count: number; window_hours: number; latest_at?: string | null; baseline_at?: string | null; keywords: BurstItem[]; industries: BurstItem[]; message: string };
export type QuadrantPoint = { industry: string; capital_score: number; public_opinion_score: number; combined_heat: number; sentiment: "positive" | "neutral" | "negative"; sentiment_score: number; capital_flow: { today?: string; five_days?: string; ten_days?: string }; quadrant: string };
export type IndustryQuadrant = { available: boolean; capital_data_mode: string; threshold: number; points: QuadrantPoint[]; axis_formula: { capital: string; public_opinion: string; bubble: string } };
export type DivergenceAlert = { industry: string; type: string; severity: "high" | "medium" | "low"; evidence: string; action: string; sources: string[]; industry_heat: number };
export type DivergenceMonitor = { available: boolean; alert_count: number; high_count: number; capital_data_mode: string; trend_baseline_ready: boolean; news_baseline_ready: boolean; alerts: DivergenceAlert[]; counts_by_type: Record<string, number>; rules: { type: string; requires_history: boolean; threshold: string }[]; message: string };
export type StockCandidate = { stock: string; industry: string; selected: boolean; association_count: number; hot_topics: { title: string; url: string; read_count: number; comment_count: number }[]; capital_rank: number; current_price: number; five_day_change_pct: number; volatility_pct: number; buy_range: number[]; stop_price: number; target_range: number[]; risk_level: string; risk_score: number; composite_score: number; industry_heat: number; selection_reasons: string[]; price_plan_type: string };
export type StockCandidatePool = { available: boolean; market_data_mode: string; stock_count?: number; stocks: StockCandidate[]; message?: string };
export type TimelineEvent = { id: string; title: string; summary: string; timestamp: string; category: string; source: string; url: string; affected_industries: string[]; affected_stocks: string[]; matched_keywords: string[]; impact_level: string };
export type EventTimeline = { available: boolean; events: TimelineEvent[]; category_counts: Record<string, number>; categories: string[]; message: string };
export type ExecutionPosition = { industry: string; stock: string; status: "已触发" | "未触发" | "已失效"; today_action: string; in_buy_range: boolean; current_price: number; simulated_entry_price: number | null; planned_amount: number; floating_return_pct: number | null; floating_profit_amount: number | null; buy_range: number[]; stop_price: number; target_range: number[]; distance_to_stop_pct: number | null; distance_to_target_pct: number | null; elapsed_trading_days: number; remaining_holding_days: number; day5_exit_reminder: string };
export type StrategyExecution = { available: boolean; execution_mode: string; broker_connected: boolean; market_data_mode?: string; generated_date?: string; current_date?: string; today_summary?: string; triggered_count?: number; pending_count?: number; invalid_count?: number; remaining_holding_days?: number; portfolio_floating_profit?: number; portfolio_floating_return_pct?: number | null; positions: ExecutionPosition[]; day5_reminder?: string; disclaimer?: string; message?: string };
export type PersistenceStatus = { enabled: boolean; engine: string; schema_version: number; database_file: string; state_restored: boolean; last_persisted_at: string; last_stage: string; counts: Record<string, number>; postgresql_ready: boolean; migration_note: string };
export type SchedulerStatus = { enabled: boolean; running: boolean; timezone?: string; calendar_mode?: string; calendar_note?: string; next_run?: { job_id: string; name: string; planned_at: string } | null; backoff_until?: string; today?: { full_runs: number; news_checks: number; skipped: number }; limits?: { full_min_interval_minutes: number; news_min_interval_minutes: number; daily_full_limit: number; daily_news_limit: number; max_backoff_minutes: number; single_flight: boolean }; jobs?: { id: string; name: string; schedule: string; action: string }[]; recent_runs?: { id: number; job_id: string; trigger_type: string; started_at: string; ended_at: string; status: string; detail?: { reason?: string; new_articles?: number; important_articles?: number; analysis_triggered?: boolean }; error?: string }[] };
export type WorkflowData = {
  stage: string;
  updated_at?: string;
  last_error?: string;
  market_data_mode?: "real" | "simulated";
  market_data_center_status?: { provider: string; data_mode: string; warning: string; layers: { scope: string; name: string; count_label: string; target_count: number; mapped_count: number; default_types: string[]; frequency: string }[]; last_run?: { scope: string; status: string; quote_count: number; capital_count: number; duration_ms: number } | null };
  real_market_quotes?: unknown[];
  real_capital_flows?: unknown[];
  collection_summary?: { guba_topic_count?: number; finance_article_count?: number };
  guba_topics?: Topic[];
  finance_commentary?: Article[];
  combined_industries?: Industry[];
  industry_network?: Network;
  industry_sentiments?: Sentiment[];
  industry_research_capital?: Capital[];
  research_capital_metadata?: { data_mode?: string; warning?: string };
  trading_strategy?: string;
  strategy_metadata?: { is_simulation?: boolean; warning?: string; as_of_date?: string };
  analysis_metadata?: { mode?: "openai" | "rule_based" | "rule_based_fallback"; fallback_used?: boolean; fallback_reason?: string };
  data_trust?: { generated_at?: string; overall_level?: "good" | "warning"; sources?: TrustSource[] };
  workflow_nodes?: WorkflowNode[];
  industry_trends?: { sample_count: number; window_hours: number; snapshots: { id: number; captured_at: string; analysis_mode: string; industry_count: number }[]; industries: IndustryTrend[] };
  strategy_evidence?: StrategyEvidence[];
  risk_control?: RiskControl;
  strategy_history?: StrategyHistory;
  sentiment_burst_radar?: BurstRadar;
  industry_quadrant?: IndustryQuadrant;
  sentiment_capital_divergence?: DivergenceMonitor;
  stock_candidate_pool?: StockCandidatePool;
  event_timeline?: EventTimeline;
  strategy_execution?: StrategyExecution;
  persistence_status?: PersistenceStatus;
  scheduler_status?: SchedulerStatus;
};

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export const demoTopics: Topic[] = [
  { rank: 1, title: "等待真实采集：股吧热门话题", read_count: 0, comment_count: 0, stocks: [] },
  { rank: 2, title: "点击「开始研判」开始抓取与分析", read_count: 0, comment_count: 0, stocks: [] },
];
export const demoIndustries: Industry[] = [
  { industry: "算力", combined_score: 91, market_hot_score: 90, policy_support_score: 86, combined_logic: "演示数据：等待真实工作流分析。", hot_topics: [], policy_signals: [] },
  { industry: "半导体", combined_score: 86, market_hot_score: 84, policy_support_score: 82, combined_logic: "演示数据：等待真实工作流分析。", hot_topics: [], policy_signals: [] },
  { industry: "机器人", combined_score: 78, market_hot_score: 81, policy_support_score: 66, combined_logic: "演示数据：等待真实工作流分析。", hot_topics: [], policy_signals: [] },
];

export function compactNumber(value = 0) {
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)}亿`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(1)}万`;
  return value.toLocaleString("zh-CN");
}

export function stageLabel(stage?: string) {
  return ({ idle: "等待运行", collecting: "正在采集", collected: "采集完成", analyzing: "正在分析", complete: "策略已生成", error: "运行异常" } as Record<string, string>)[stage || "idle"] || stage || "未知";
}

export function freshnessLabel(value: TrustSource["freshness"]) {
  return ({ fresh: "新鲜", warning: "注意", stale: "过期", not_run: "未运行", unknown: "未知" } as const)[value] || "未知";
}

export function durationLabel(minutes?: number | null) {
  if (minutes == null) return "—";
  if (minutes < 60) return `${Math.round(minutes)} 分钟`;
  if (minutes < 1_440) return `${(minutes / 60).toFixed(1)} 小时`;
  return `${(minutes / 1_440).toFixed(1)} 天`;
}

export function nodeStatusLabel(value: WorkflowNode["status"]) {
  return ({ waiting: "等待", running: "运行中", success: "成功", failed: "失败" } as const)[value];
}

export function nodeModeLabel(value?: string) {
  return ({ crawler: "采集器", openai: "大模型", rule_based: "纯规则", rule_based_fallback: "规则降级", deterministic: "确定性程序" } as Record<string, string>)[value || ""] || "待运行";
}

export function timeLabel(value?: string) {
  return value ? new Date(value).toLocaleTimeString("zh-CN", { hour12: false }) : "—";
}

export function PanelTitle({ eyebrow, title, action }: { eyebrow: string; title: string; action?: string }) {
  return <div className="panel-title"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div>{action && <span className="panel-note">{action}</span>}</div>;
}

export function useSentraData() {
  const [data, setData] = useState<WorkflowData>({ stage: "idle" });
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [apiOnline, setApiOnline] = useState(false);
  const [modelConfigured, setModelConfigured] = useState(false);
  const [engine, setEngine] = useState<"rule" | "llm">("rule");
  const [marketMode, setMarketMode] = useState<"simulated" | "real">("simulated");
  const [researchFocus, setResearchFocus] = useState<{ target_type?: string; target_name?: string; period?: string; submitted_at?: string }>({});

  const refreshLatest = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/workflow/latest`);
      const payload = await response.json();
      if (payload.success && payload.data) {
        setData(payload.data);
        if (payload.data.market_data_mode) setMarketMode(payload.data.market_data_mode);
        if (payload.data.research_focus) setResearchFocus(payload.data.research_focus);
      }
      return payload;
    } catch {
      setApiOnline(false);
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [healthRes, latestRes] = await Promise.all([
          fetch(`${API_BASE}/api/health`).then((response) => response.json()),
          fetch(`${API_BASE}/api/workflow/latest`).then((response) => response.json()),
        ]);
        if (cancelled) return;
        setApiOnline(Boolean(healthRes.success));
        setModelConfigured(Boolean(healthRes.model_configured));
        const backendEngine = String(healthRes.analysis_engine || "auto");
        if (backendEngine === "llm") setEngine("llm");
        else if (backendEngine === "rule") setEngine("rule");
        else setEngine(healthRes.model_configured ? "llm" : "rule");
        if (latestRes.success && latestRes.data) {
          setData(latestRes.data);
          if (latestRes.data.market_data_mode) setMarketMode(latestRes.data.market_data_mode);
          if (latestRes.data.research_focus) setResearchFocus(latestRes.data.research_focus);
        }
      } catch {
        if (cancelled) return;
        setApiOnline(false);
        setNotice("后端 API 尚未启动，请先启动本地服务。");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const runAction = useCallback(async (path: string, label: string, body?: Record<string, unknown>) => {
    setBusy(label);
    setNotice(`${label}已启动，请等待节点执行完成…`);
    const poller = window.setInterval(() => {
      refreshLatest().catch(() => undefined);
    }, 800);
    try {
      const init: RequestInit = { method: "POST", headers: { "Content-Type": "application/json" } };
      if (body && Object.keys(body).length > 0) {
        init.body = JSON.stringify(body);
      }
      const response = await fetch(`${API_BASE}${path}`, init);
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || "请求失败");
      setData(payload.data);
      setApiOnline(true);
      setNotice(`${label}完成，数据已刷新。`);
      if (payload.data?.research_focus) {
        setResearchFocus(payload.data.research_focus);
      }
      return payload;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setNotice(message);
      if (message.includes("fetch")) setApiOnline(false);
      return null;
    } finally {
      window.clearInterval(poller);
      setBusy("");
    }
  }, [refreshLatest]);

  const switchEngine = useCallback(async (next: "rule" | "llm") => {
    if (busy || next === engine) return;
    setBusy("切换模式");
    try {
      const response = await fetch(`${API_BASE}/api/workflow/engine`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ engine: next }) });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || "请求失败");
      setEngine(next);
      setApiOnline(true);
      setNotice(next === "rule" ? "已切换为「选择规则」模式。" : modelConfigured ? "已切换为「接入 API」模式。" : "已选择「接入 API」，但未配置 OPENAI_API_KEY，将回退规则模式。");
      await refreshLatest();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setNotice(message);
      if (message.includes("fetch")) setApiOnline(false);
    } finally {
      setBusy("");
    }
  }, [busy, engine, modelConfigured, refreshLatest]);

  const switchMarketMode = useCallback(async (next: "simulated" | "real") => {
    if (busy || next === marketMode) return;
    setBusy("切换行情模式");
    try {
      const response = await fetch(`${API_BASE}/api/workflow/market-mode`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: next }) });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || "请求失败");
      setMarketMode(next);
      setNotice(next === "real" ? "已切换为「真实」行情模式。" : "已切换为「模拟」行情模式。");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setNotice(message);
      if (message.includes("fetch")) setApiOnline(false);
    } finally {
      setBusy("");
    }
  }, [busy, marketMode]);

  // Derived data
  const industries = (data.combined_industries?.length ? data.combined_industries : demoIndustries).slice(0, 6);
  const sentiments = useMemo(() => data.industry_sentiments || [], [data.industry_sentiments]);
  const capital = data.industry_research_capital || [];
  const network = data.industry_network || {};
  const trustSources = data.data_trust?.sources || [];
  const workflowNodes = data.workflow_nodes || [];
  const trendData = data.industry_trends;
  const industryTrends = useMemo(() => trendData?.industries || [], [trendData?.industries]);
  const evidenceChains = data.strategy_evidence || [];
  const risk = data.risk_control;
  const history = data.strategy_history;
  const burstRadar = data.sentiment_burst_radar;
  const quadrant = data.industry_quadrant;
  const divergence = data.sentiment_capital_divergence;
  const stockPool = data.stock_candidate_pool;
  const eventTimeline = data.event_timeline;
  const execution = data.strategy_execution;
  const persistence = data.persistence_status;
  const scheduler = data.scheduler_status;
  const topics = (data.guba_topics?.length ? data.guba_topics : demoTopics).slice(0, 6);
  const articles = (data.finance_commentary || []).slice(0, 4);
  const isDemo = !data.combined_industries?.length;
  const averageSentiment = useMemo(() => sentiments.length ? Math.round(sentiments.reduce((sum, item) => sum + item.sentiment_score, 0) / sentiments.length) : 50, [sentiments]);
  const coreIndustry = network.core_industries?.[0] || industries[0]?.industry || "待分析";
  const coreRelations = network.industry_relations?.[coreIndustry];
  const analysisMode = nodeModeLabel(data.analysis_metadata?.mode);

  const sortedStocks = useMemo(() => [...(stockPool?.stocks || [])].sort((a, b) => b.composite_score - a.composite_score), [stockPool?.stocks]);
  const recommendedStocks = useMemo(() => sortedStocks.filter((item) => item.selected).slice(0, 6), [sortedStocks]);

  return {
    data, setData, busy, notice, apiOnline, modelConfigured, engine, marketMode, researchFocus,
    runAction, switchEngine, switchMarketMode, refreshLatest,
    industries, sentiments, capital, network, trustSources, workflowNodes,
    industryTrends, evidenceChains, risk, history, burstRadar, quadrant,
    divergence, stockPool, eventTimeline, execution, persistence, scheduler,
    topics, articles, isDemo, averageSentiment, coreIndustry, coreRelations,
    analysisMode, sortedStocks, recommendedStocks,
  };
}