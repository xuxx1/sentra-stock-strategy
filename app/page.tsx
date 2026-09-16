"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSentraData, stageLabel, type StockCandidate } from "./lib/use-sentra-data";
import "./home-extra.css";

type ResearchPeriod = "3" | "5" | "10";

function stanceFromScore(score: number) {
  if (score >= 85) return { label: "积极关注", tone: "positive" };
  if (score >= 70) return { label: "谨慎关注", tone: "cautious" };
  if (score >= 55) return { label: "中性", tone: "neutral" };
  return { label: "回避", tone: "avoid" };
}

export default function Home() {
  const sentra = useSentraData();
  const { data, busy, notice, apiOnline, modelConfigured, engine, marketMode, runAction, switchEngine, switchMarketMode } = sentra;
  const { industries, sentiments, recommendedStocks, analysisMode, isDemo, coreIndustry, coreRelations, history } = sentra;

  const [period, setPeriod] = useState<ResearchPeriod>("5");
  const [localEngine, setLocalEngine] = useState<"rule" | "llm">(engine);
  const [localMarket, setLocalMarket] = useState<"simulated" | "real">(marketMode);

  useEffect(() => { setLocalEngine(engine); }, [engine]);
  useEffect(() => { setLocalMarket(marketMode); }, [marketMode]);

  const topIndustry = industries[0];
  const { label: stanceLabel, tone: stanceTone } = stanceFromScore(topIndustry?.combined_score ?? 0);
  const mainDirection = industries.slice(0, 2).map((item) => item.industry).join(" / ") || "等待研判";
  const evidencePoints = useMemo(() => {
    const points: string[] = [];
    if (topIndustry?.combined_logic) points.push(topIndustry.combined_logic);
    topIndustry?.hot_topics?.slice(0, 2).forEach((t) => { if (t) points.push(`舆情：${t}`); });
    topIndustry?.policy_signals?.slice(0, 2).forEach((t) => { if (t) points.push(`政策：${t}`); });
    if (points.length === 0 && isDemo) points.push("等待运行研判流程，结果将基于真实舆情、资金、政策数据生成。");
    if (points.length === 0) points.push("等待研判完成后生成判断依据。");
    return points.slice(0, 4);
  }, [topIndustry, isDemo]);

  const opportunityPoints = useMemo(() => {
    const items = recommendedStocks.flatMap((stock) => stock.selection_reasons.slice(0, 2));
    if (!items.length && topIndustry) items.push(`${topIndustry.industry}：综合分 ${topIndustry.combined_score} · ${stanceLabel}`);
    if (!items.length) items.push("等待研判完成后展示主要机会。");
    return Array.from(new Set(items)).slice(0, 4);
  }, [recommendedStocks, topIndustry, stanceLabel]);

  const riskPoints = useMemo(() => {
    const items: string[] = [];
    sentiments.slice(0, 3).forEach((item) => item.risk_factors.forEach((r) => { if (r) items.push(`${item.industry}：${r}`); }));
    if (!items.length && isDemo) items.push("等待真实舆情风险因子接入。");
    if (!items.length) items.push("当前未触发显著风险因子。");
    return items.slice(0, 4);
  }, [sentiments, isDemo]);

  const strategyCards = recommendedStocks.slice(0, 3);
  const strategyInvalidation = history?.failure_cases?.[0]?.reason || "当推荐行业综合分跌破 60、舆情与资金显著背离或触发止损价时策略失效。";
  const headlineRisk = riskPoints[0] || "策略失效条件：当综合分跌破 60、舆情与资金背离、或触发止损价时策略失效。";
  const topThreeIndustries = industries.slice(0, 3);
  const lastRunAt = data.updated_at ? new Date(data.updated_at).toLocaleTimeString("zh-CN", { hour12: false }) : "—";

  const onStartResearch = async () => {
    if (!apiOnline) return;
    if (localEngine !== engine) {
      await switchEngine(localEngine);
    }
    if (localMarket !== marketMode) {
      await switchMarketMode(localMarket);
    }
    await runAction("/api/workflow/analyze", "开始研判", {
      period,
      analysis_engine: localEngine === "llm" ? "llm" : "rule",
      market_data_mode: localMarket,
    });
  };

  const canSubmit = !busy && apiOnline;

  return (
    <main className="dashboard-shell home-shell">
      {/* ① 顶部导航 */}
      <header className="topbar">
        <div className="brand"><div className="brand-mark">S</div><div><strong>舆策 · SENTRA</strong><span>舆情驱动的短线策略决策系统</span></div></div>
        <nav className="main-nav" aria-label="主导航">
          <Link href="/" className="active">首页</Link>
          <Link href="/analysis">详细分析</Link>
          <Link href="/portfolio">策略与回测</Link>
          <Link href="/admin">系统管理</Link>
        </nav>
        <div className="system-status engine-switch">
          <span className={`status-dot ${apiOnline ? "" : "offline"}`} />
          <div className="engine-options" role="group" aria-label="研判引擎">
            <button type="button" className={engine === "rule" ? "active" : ""} disabled={Boolean(busy)} onClick={() => switchEngine("rule")}>规则模式</button>
            <button type="button" className={engine === "llm" ? "active" : ""} disabled={Boolean(busy)} onClick={() => switchEngine("llm")}>AI API 模式</button>
          </div>
          <small>{engine === "rule" ? "纯规则可运行" : modelConfigured ? "大模型分析" : "未配置 API · 规则兜底"} · API {apiOnline ? "在线" : "离线"}</small>
        </div>
      </header>

      {(notice || data.last_error) && <div className={`notice-bar ${(data.stage === "error" || (!apiOnline && notice)) ? "error" : ""}`}><span>{data.stage === "error" ? "!" : "i"}</span>{data.last_error || notice}</div>}

      {/* ② 研判输入区 */}
      <section className="research-input" aria-label="研判输入区">
        <div className="panel-title">
          <div><span className="eyebrow">RESEARCH INPUT</span><h2>研判输入</h2><p>点击「开始研判」后系统自动采集舆情、按综合分锁定前 3 行业并生成 5 日策略。</p></div>
          <span className="panel-note">阶段：{stageLabel(data.stage)} · 最近更新 {lastRunAt}</span>
        </div>
        <div className="research-grid">
          <label className="field">
            <span>策略周期</span>
            <div className="segmented">
              {(["3", "5", "10"] as ResearchPeriod[]).map((p) => (
                <button type="button" key={p} className={period === p ? "active" : ""} disabled={Boolean(busy)} onClick={() => setPeriod(p)}>{p} 日{p === "5" ? " · 默认" : ""}</button>
              ))}
            </div>
          </label>
          <label className="field">
            <span>研判引擎</span>
            <div className="segmented">
              <button type="button" className={localEngine === "rule" ? "active" : ""} disabled={Boolean(busy)} onClick={() => setLocalEngine("rule")}>规则</button>
              <button type="button" className={localEngine === "llm" ? "active" : ""} disabled={Boolean(busy)} onClick={() => setLocalEngine("llm")}>AI API</button>
            </div>
          </label>
          <label className="field">
            <span>行情模式</span>
            <div className="segmented">
              <button type="button" className={localMarket === "simulated" ? "active" : ""} disabled={Boolean(busy)} onClick={() => setLocalMarket("simulated")}>模拟</button>
              <button type="button" className={localMarket === "real" ? "active" : ""} disabled={Boolean(busy)} onClick={() => setLocalMarket("real")}>真实</button>
            </div>
          </label>
        </div>
        <div className="research-actions">
          <button type="button" className="primary-cta" disabled={!canSubmit} onClick={onStartResearch}>{busy ? "研判中…" : "开始研判"}</button>
          <small className="research-hint">系统将基于最新舆情自动挑选前 3 行业 · {period} 日 · {localEngine === "llm" ? "AI API" : "规则"} · {localMarket === "real" ? "真实行情" : "模拟行情"}</small>
        </div>
      </section>

      {/* ③ AI/规则综合研判 */}
      <section className="research-judgment" aria-label="综合研判">
        <div className="panel-title">
          <div><span className="eyebrow">COMPREHENSIVE JUDGMENT</span><h2>综合研判</h2><p>一句话定位现状 + 主线方向 + 判断依据 + 机会与风险。</p></div>
          <span className="panel-note">{analysisMode}</span>
        </div>
        <div className="judgment-focus" role="status" aria-live="polite">
          <span className="eyebrow">本次自动锁定的 Top 3 行业</span>
          <p>
            {topThreeIndustries.length > 0 ? topThreeIndustries.map((item) => (
              <b key={item.industry} title={`综合分 ${item.combined_score}`}>
                {item.industry}
                <span className="dim"> · {item.combined_score}</span>
              </b>
            )) : <i>等待运行研判…</i>}
            <em>{period} 日策略</em>
            <em>{localEngine === "llm" ? "AI API" : "规则"}</em>
            <em>{localMarket === "real" ? "真实行情" : "模拟行情"}</em>
          </p>
          <small className="dim">系统按综合分排序，自动锁定前 3 行业；不需要你手动指定行业。Last run {lastRunAt}</small>
        </div>
        <div className="judgment-grid">
          <div className="judgment-status">
            <span>当前状态</span>
            <b className={`stance-pill stance-${stanceTone}`}>{stanceLabel}</b>
            <small>{topIndustry ? `${topIndustry.industry} 综合分 ${topIndustry.combined_score}` : "等待首次研判"}</small>
          </div>
          <div className="judgment-main">
            <span>主线方向</span>
            <b>{mainDirection}</b>
          </div>
          <div className="judgment-core">
            <span>核心判断</span>
            <b>{topIndustry?.combined_logic || (isDemo ? "等待运行研判后生成核心判断。" : "暂无核心判断")}</b>
          </div>
          <div className="judgment-evidence">
            <span>判断依据</span>
            <ul>{evidencePoints.map((p, i) => <li key={i}>{p}</li>)}</ul>
          </div>
          <div className="judgment-opportunity">
            <span>主要机会</span>
            <ul>{opportunityPoints.map((p, i) => <li key={i}>{p}</li>)}</ul>
          </div>
          <div className="judgment-risk">
            <span>主要风险</span>
            <ul>{riskPoints.map((p, i) => <li key={i}>{p}</li>)}</ul>
          </div>
        </div>
      </section>

      {/* ④ 5日短线策略 */}
      <section className="strategy-cards" aria-label="5日短线策略">
        <div className="panel-title">
          <div><span className="eyebrow">5-DAY TRADING STRATEGY</span><h2>5 日短线策略</h2><p>每张卡片对应一个核心行业的最优 1 只股票，含价格区间与策略倾向。</p></div>
          <span className="panel-note">Top {topThreeIndustries.length} 行业 / {strategyCards.length} 只入选 · 最近刷新 {lastRunAt}</span>
        </div>
        {strategyCards.length > 0 ? (
          <div className={`strategy-grid cols-${strategyCards.length}`}>
            {strategyCards.map((item) => <StrategyCard key={`${item.industry}-${item.stock}`} stock={item} />)}
          </div>
        ) : (
          <div className="strategy-empty">
            <p>尚未生成最终推荐股票。点击「开始研判」让系统采集舆情并生成候选。</p>
            {recommendedStocks.length === 0 && isDemo && <small className="dim">演示模式：等待首次真实工作流运行。</small>}
          </div>
        )}
      </section>

      {/* ⑤ 底部风险提示 */}
      <footer className="home-footer">
        <div className="risk-note">
          <span className="eyebrow">RISK & INVALIDATION</span>
          <div><b>主要风险</b><p>{headlineRisk}</p></div>
          <div><b>策略失效条件</b><p>{strategyInvalidation}</p></div>
        </div>
        <div className="home-footer-actions">
          <Link href="/analysis" className="primary-cta secondary">查看详细分析</Link>
          <Link href="/portfolio" className="primary-cta secondary">策略执行与回测</Link>
        </div>
        <div className="home-foot-meta">
          <span>主线：{coreIndustry}</span>
          <span>关联：{coreRelations?.related?.slice(0, 3).join(" · ") || "—"}</span>
          <span>研判引擎：{analysisMode}</span>
          <span>系统输出仅供研究决策辅助，不构成投资建议。</span>
        </div>
      </footer>
    </main>
  );
}

function StrategyCard({ stock }: { stock: StockCandidate }) {
  const stance = stock.risk_level === "low" ? "积极关注" : stock.risk_level === "medium" ? "谨慎关注" : "回避";
  const stanceTone = stock.risk_level === "low" ? "positive" : stock.risk_level === "medium" ? "cautious" : "avoid";
  const reason = stock.selection_reasons[0] || `${stock.industry} 综合分 ${stock.composite_score} · 资金排名 ${stock.capital_rank}`;
  return (
    <article className="strategy-card">
      <header>
        <div><b>{stock.stock}</b><small>{stock.industry} · 资金 #{stock.capital_rank}</small></div>
        <span className={`stance-pill stance-${stanceTone}`}>{stance}</span>
      </header>
      <dl className="strategy-prices">
        <div><dt>当前价</dt><dd>¥{stock.current_price.toFixed(2)}<small className={stock.five_day_change_pct >= 0 ? "up" : "down"}>{stock.five_day_change_pct >= 0 ? "+" : ""}{stock.five_day_change_pct}% · 5日</small></dd></div>
        <div><dt>关注区间</dt><dd>¥{stock.buy_range[0]} – ¥{stock.buy_range[1]}</dd></div>
        <div><dt>目标区间</dt><dd>¥{stock.target_range[0]} – ¥{stock.target_range[1]}</dd></div>
        <div><dt>风险控制</dt><dd className="stop">¥{stock.stop_price}</dd></div>
      </dl>
      <p className="strategy-reason">{reason}</p>
      <footer><span>综合分 {stock.composite_score}</span><span>{stock.risk_level}风险 · {stock.price_plan_type}</span></footer>
    </article>
  );
}