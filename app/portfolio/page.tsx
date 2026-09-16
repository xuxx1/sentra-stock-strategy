"use client";

import Link from "next/link";
import { useState } from "react";
import {
  durationLabel,
  nodeModeLabel,
  timeLabel,
  useSentraData,
} from "../lib/use-sentra-data";

function RiskMetric({ label, value, tone }: { label: string; value: string; tone?: "risk" | "cash" }) {
  return <div className={`risk-metric ${tone || ""}`}><span>{label}</span><b>{value}</b></div>;
}

function BacktestMetric({ label, value }: { label: string; value: string }) {
  return <div className="risk-metric"><span>{label}</span><b>{value}</b></div>;
}

export default function PortfolioPage() {
  const sentra = useSentraData();
  const { data, busy, runAction, risk, execution, history, apiOnline } = sentra;
  const [showStressTest, setShowStressTest] = useState(false);
  const verifiedCount = history?.verified_5d_count || 0;
  const archivedCount = history?.archived_count || 0;
  const hasBacktestData = verifiedCount >= 5;

  return (
    <main className="dashboard-shell">
      <header className="topbar">
        <div className="brand"><div className="brand-mark">S</div><div><strong>舆策 · SENTRA</strong><span>策略执行与历史回测</span></div></div>
        <nav className="main-nav" aria-label="主导航">
          <Link href="/">首页</Link>
          <Link href="/analysis">详细分析</Link>
          <Link href="/portfolio" className="active">策略与回测</Link>
          <Link href="/admin">系统管理</Link>
        </nav>
        <div className="system-status engine-switch">
          <span className={`status-dot ${apiOnline ? "" : "offline"}`} />
          <small>阶段：{data.stage} · API {apiOnline ? "在线" : "离线"}</small>
        </div>
      </header>

      <section className="execution-risk-center" aria-label="策略执行与风控">
        <div className="execution-heading"><div><span className="eyebrow">PAPER EXECUTION & RISK CONTROL</span><h2>策略执行与风控</h2><p>组合风险与个股模拟执行集中观察；不连接券商，不发送任何真实委托。</p></div><div className={`risk-level ${risk?.alerts?.some((item) => item.level === "high") ? "high" : "normal"}`}><span>模拟交易 · 当前风险</span><b>{!risk?.available ? "等待策略" : risk.alerts?.some((item) => item.level === "high") ? "需要处置" : risk.alerts?.length ? "保持警戒" : "风险可控"}</b></div></div>
        {execution?.available && risk?.available ? <>
          <div className="execution-command"><div><span>今日应该做什么</span><b>{execution.today_summary}</b><small>{execution.day5_reminder}</small></div><div className="execution-counts"><span><b>{execution.triggered_count}</b>已触发</span><span><b>{execution.pending_count}</b>未触发</span><span><b>{execution.invalid_count}</b>已失效</span></div></div>
          <div className="execution-risk-metrics"><RiskMetric label="当前组合盈亏" value={execution.portfolio_floating_return_pct == null ? "无持仓" : `${execution.portfolio_floating_return_pct > 0 ? "+" : ""}${execution.portfolio_floating_return_pct}% · ${(execution.portfolio_floating_profit || 0) >= 0 ? "+" : ""}¥${(execution.portfolio_floating_profit || 0).toFixed(2)}`} /><RiskMetric label="最大风险" value={`${risk.max_risk_pct}% · ¥${risk.max_risk_amount?.toFixed(2)}`} tone="risk" /><RiskMetric label="剩余现金" value={`¥${risk.remaining_cash?.toFixed(2)}`} tone="cash" /><RiskMetric label="风险警报" value={`${risk.alerts?.length || 0} 条 · 负面新闻 ${risk.negative_news_count || 0}`} tone={risk.alerts?.length ? "risk" : undefined} /></div>
          <div className="execution-alert-strip"><span>组合约束</span><b>单股 ≤ {risk.max_stock_position_pct}%</b><b>单行业 ≤ {risk.max_industry_position_pct}%</b><b>集中度 {risk.concentration_index} · {risk.concentration_level}</b><b>收益风险比 {risk.reward_risk_ratio == null ? "—" : `${risk.reward_risk_ratio}:1`}</b></div>
          {!!risk.alerts?.length && <div className="execution-alert-list">{risk.alerts.slice(0, 3).map((item, index) => <article className={item.level} key={`${item.type}-${index}`}><span>{item.type}</span><p>{item.message}</p></article>)}</div>}
          <div className="execution-subheading"><div><h3>个股执行状态</h3><p>入场、浮盈亏、止损目标与剩余持有期统一跟踪</p></div><span>{execution.positions.length} 个执行标的</span></div>
          <div className="execution-positions">{execution.positions.map((item) => <article className={`execution-card status-${item.status}`} key={item.stock}><div className="execution-card-head"><div><b>{item.stock}</b><small>{item.industry}</small></div><span>{item.status}</span></div><div className="execution-price"><div><span>当前价格</span><b>¥{item.current_price.toFixed(2)}</b></div><div><span>买入区间</span><b>¥{item.buy_range[0]}–{item.buy_range[1]}</b><small className={item.in_buy_range ? "in-range" : ""}>{item.in_buy_range ? "已进入区间" : "尚未进入"}</small></div></div><div className="execution-pnl"><div><span>当前浮动收益</span><b className={(item.floating_return_pct || 0) >= 0 ? "positive" : "negative"}>{item.floating_return_pct == null ? "未建仓" : `${item.floating_return_pct > 0 ? "+" : ""}${item.floating_return_pct}%`}</b><small>{item.floating_profit_amount == null ? "等待触发" : `${item.floating_profit_amount >= 0 ? "+" : ""}¥${item.floating_profit_amount.toFixed(2)}`}</small></div><div><span>距离止损价</span><b>{item.distance_to_stop_pct == null ? "—" : `${item.distance_to_stop_pct.toFixed(2)}%`}</b><small>止损 ¥{item.stop_price}</small></div><div><span>距离目标价</span><b>{item.distance_to_target_pct == null ? "—" : `${item.distance_to_target_pct > 0 ? "+" : ""}${item.distance_to_target_pct.toFixed(2)}%`}</b><small>目标 ¥{item.target_range[0]}–{item.target_range[1]}</small></div></div><div className="holding-progress"><div><span>已过 {item.elapsed_trading_days} 日</span><span>剩余 {item.remaining_holding_days} 日</span></div><i><em style={{ width: `${Math.min(100, item.elapsed_trading_days / 5 * 100)}%` }} /></i></div><footer><b>今日动作</b><p>{item.today_action}</p><small>{item.day5_exit_reminder}</small></footer></article>)}</div>
          <div className="stress-test-fold"><button type="button" onClick={() => setShowStressTest((value) => !value)}><span><b>5 日组合情景压力测试</b><small>基于目标区间与止损价的确定性测算</small></span><strong>{showStressTest ? "收起 ↑" : "展开 ↓"}</strong></button>{showStressTest && <div className="scenario-cards">{risk.scenarios?.map((item) => <article className={item.name === "乐观" ? "optimistic" : item.name === "悲观" ? "pessimistic" : "baseline"} key={item.name}><span>{item.name}</span><b>{item.result_pct > 0 ? "+" : ""}{item.result_pct}%</b><small>{item.result_amount > 0 ? "+" : ""}¥{item.result_amount.toFixed(2)}</small><p>{item.advice}</p></article>)}</div>}</div>
          <p className="execution-disclaimer">{execution.disclaimer} {risk.calculation_note}</p>
        </> : <div className="execution-empty">{execution?.message || risk?.message || "策略报告生成后显示组合风险和模拟执行状态。"}</div>}
      </section>

      {!hasBacktestData ? <section className="backtest-summary-card" aria-label="历史回测摘要">
        <div><span className="eyebrow">HISTORICAL VALIDATION</span><h2>历史回测与策略复盘</h2><p>真实 5 日样本积累到 5 个后，自动展开胜率、收益、回撤、行业表现与失败案例。</p></div>
        <div className="backtest-summary-stats"><span><small>已归档</small><b>{archivedCount}<em> 次</em></b></span><i /><span><small>真实验证</small><b>{verifiedCount}<em> / 5 次</em></b></span><i /><span className="simulation-note"><small>统计口径</small><b>模拟策略不计入胜率</b></span></div>
        <button disabled={Boolean(busy)} onClick={() => runAction("/api/history/refresh", "刷新真实表现")}>刷新验证进度</button>
      </section> : <section className="backtest-center" aria-label="历史回测与策略复盘">
        <div className="backtest-heading"><div><span className="eyebrow">HISTORICAL VALIDATION</span><h2>历史回测与策略复盘</h2><p>归档每次生成时的舆情、推荐、入场区间、目标价、止损价与市场价格，按真实交易日持续验证。</p></div><div className="validation-actions"><button disabled={Boolean(busy)} onClick={() => runAction("/api/history/refresh", "刷新真实表现")}>刷新 1 / 3 / 5 日表现</button><div className="validation-progress"><span>已验证 / 已归档</span><b>{verifiedCount}<small> / {archivedCount}</small></b></div></div></div>
        <div className="backtest-metrics"><BacktestMetric label="近30次策略胜率" value={history?.win_rate == null ? "待样本" : `${history.win_rate}%`} /><BacktestMetric label="平均5日收益率" value={history?.average_5d_return == null ? "待样本" : `${history.average_5d_return > 0 ? "+" : ""}${history.average_5d_return}%`} /><BacktestMetric label="平均最大回撤" value={history?.average_max_drawdown == null ? "待样本" : `${history.average_max_drawdown}%`} /><BacktestMetric label="盈亏比" value={history?.profit_loss_ratio == null ? "待样本" : `${history.profit_loss_ratio}:1`} /><BacktestMetric label="策略超额收益" value={history?.excess_return.available ? `${history.excess_return.value}%` : "待基准"} /><BacktestMetric label="模拟档案" value={`${history?.simulation_only_count || 0} 次`} /> </div>
        <div className="backtest-grid"><section className="backtest-box"><h3>最近策略档案<span>1 / 3 / 5 日追踪</span></h3><div className="archive-list">{history?.recent_strategies?.map((item) => <article key={item.id}><time>{new Date(item.generated_at).toLocaleString("zh-CN", { hour12: false })}</time><div><b>{item.industries.join(" / ")}</b><small>{item.stocks.join("、")} · {nodeModeLabel(item.analysis_mode)}</small></div><span className={item.market_data_mode === "real" ? "actual" : "simulation"}>{item.market_data_mode === "real" ? item.verified_days >= 5 ? "5日已验证" : `待验证 D${item.verified_days}` : "模拟归档"}</span></article>)}{!history?.recent_strategies?.length && <p className="backtest-empty">下一次策略生成后建立首条档案</p>}</div></section><section className="backtest-box"><h3>规则模式 / AI 模式对比</h3><div className="mode-compare">{history?.mode_comparison?.map((item) => <div key={item.mode}><span>{nodeModeLabel(item.mode)}</span><b>{item.verified_count}<small> 个5日样本</small></b><em>{item.average_return == null ? "暂无可比结果" : `均值 ${item.average_return}% · 胜率 ${item.win_rate}%`}</em></div>)}</div><p className="benchmark-note">{history?.excess_return.message || "基准指数接入后计算策略超额收益。"}</p></section></div>
        <div className="backtest-grid lower"><section className="backtest-box"><h3>不同行业策略表现</h3>{history?.industry_performance?.length ? <div className="industry-performance">{history.industry_performance.map((item) => <div key={item.industry}><b>{item.industry}</b><span>{item.samples} 次</span><em>{item.average_return > 0 ? "+" : ""}{item.average_return}%</em><small>胜率 {item.win_rate}%</small></div>)}</div> : <p className="backtest-empty">尚无完成5日真实验证的行业样本</p>}</section><section className="backtest-box failure-box"><h3>失败案例复盘</h3>{history?.failure_cases?.length ? history.failure_cases.map((item) => <div className="failure-case" key={item.run_id}><b>策略 #{item.run_id} · {item.return_pct}%</b><p>{item.reason}</p></div>) : <p className="backtest-empty">没有可复盘的真实失败案例；模拟策略不会被伪装成失败样本。</p>}</section></div>
        <p className="backtest-method">{history?.methodology || "策略生成后开始积累可验证历史。"}</p>
      </section>}
    </main>
  );
}