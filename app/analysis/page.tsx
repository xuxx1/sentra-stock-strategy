"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  PanelTitle,
  compactNumber,
  durationLabel,
  freshnessLabel,
  useSentraData,
  type BurstItem,
  type StockCandidate,
  type TimelineEvent,
  type TrendPoint,
} from "../lib/use-sentra-data";
import "../analysis-extra.css";

type DetailSub = "trends" | "sentiment" | "capital" | "timeline" | "quadrant" | "stocks" | "sources";

const SUB_TABS: { key: DetailSub; label: string }[] = [
  { key: "trends", label: "热点趋势" },
  { key: "sentiment", label: "行业情绪" },
  { key: "capital", label: "资金流" },
  { key: "timeline", label: "新闻时间轴" },
  { key: "quadrant", label: "行业四象限" },
  { key: "stocks", label: "候选股票" },
  { key: "sources", label: "数据来源" },
];

export default function AnalysisPage() {
  const sentra = useSentraData();
  const { data, industries, sentiments, capital, industryTrends, burstRadar, quadrant, divergence, stockPool, eventTimeline, topics, articles, isDemo } = sentra;
  const [sub, setSub] = useState<DetailSub>("trends");
  const [hotspotTab, setHotspotTab] = useState<"industries" | "keywords" | "news">("industries");
  const [hotspotExpanded, setHotspotExpanded] = useState(false);
  const [eventCategory, setEventCategory] = useState("全部");
  const [eventSource, setEventSource] = useState<"全部来源" | "财经资讯" | "股吧话题">("全部来源");
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(null);
  const [stockSort, setStockSort] = useState<"composite" | "capital" | "heat" | "risk">("composite");

  const risingIndustries = useMemo(() => [...industryTrends].sort((a, b) => b.score_change_24h - a.score_change_24h || a.current_rank - b.current_rank), [industryTrends]);
  const activeKeywords = useMemo(() => [...(burstRadar?.keywords || [])].filter((item) => item.is_new || (item.discussion_delta_1h || 0) > 0 || (item.read_growth_rate || 0) > 0 || (item.comment_growth_rate || 0) > 0 || (item.news_growth_rate || 0) > 0).sort((a, b) => b.burst_score - a.burst_score), [burstRadar?.keywords]);
  const newsIncrements = useMemo(() => [...(burstRadar?.keywords || []), ...(burstRadar?.industries || [])].filter((item) => (item.news_growth_rate || 0) > 0).sort((a, b) => (b.news_growth_rate || 0) - (a.news_growth_rate || 0) || b.burst_score - a.burst_score), [burstRadar?.keywords, burstRadar?.industries]);
  const attentionChanges = useMemo(() => {
    const changes: { tone: string; title: string; detail: string }[] = [];
    risingIndustries.filter((item) => item.score_change_24h > 0 || item.rank_change_24h > 0).slice(0, 2).forEach((item) => changes.push({ tone: "up", title: `${item.industry}正在升温`, detail: `热度 ${item.score_change_24h > 0 ? "+" : ""}${item.score_change_24h} · 排名${item.rank_change_24h > 0 ? `上升${item.rank_change_24h}位` : "保持"}` }));
    const burst = activeKeywords[0];
    if (burst) changes.push({ tone: "burst", title: `${burst.name}${burst.is_new ? "首次出现" : "出现爆发"}`, detail: `${burst.source} · 1小时新增讨论 ${burst.discussion_delta_1h ?? "—"}` });
    const cooling = [...industryTrends].sort((a, b) => a.score_change_24h - b.score_change_24h)[0];
    if (changes.length < 3 && cooling?.score_change_24h < 0) changes.push({ tone: "down", title: `${cooling.industry}快速降温`, detail: `热度 ${cooling.score_change_24h} · 当前排名 ${cooling.current_rank}` });
    return changes.slice(0, 3);
  }, [activeKeywords, industryTrends, risingIndustries]);

  const visibleEvents = useMemo(() => (eventTimeline?.events || []).filter((item) => (eventCategory === "全部" || item.category === eventCategory) && (eventSource === "全部来源" || (eventSource === "股吧话题" ? item.source.includes("股吧") : !item.source.includes("股吧")))), [eventTimeline?.events, eventCategory, eventSource]);
  const eventSourceCount = (source: "全部来源" | "财经资讯" | "股吧话题") => source === "全部来源" ? eventTimeline?.events?.length || 0 : (eventTimeline?.events || []).filter((item) => source === "股吧话题" ? item.source.includes("股吧") : !item.source.includes("股吧")).length;

  const sortedStocks = useMemo(() => [...(stockPool?.stocks || [])].sort((a, b) => stockSort === "capital" ? a.capital_rank - b.capital_rank || b.composite_score - a.composite_score : stockSort === "heat" ? b.industry_heat - a.industry_heat || b.composite_score - a.composite_score : stockSort === "risk" ? a.risk_score - b.risk_score || b.composite_score - a.composite_score : b.composite_score - a.composite_score), [stockPool?.stocks, stockSort]);

  const averageSentiment = useMemo(() => sentiments.length ? Math.round(sentiments.reduce((sum, item) => sum + item.sentiment_score, 0) / sentiments.length) : 50, [sentiments]);

  return (
    <main className="dashboard-shell">
      <header className="topbar">
        <div className="brand"><div className="brand-mark">S</div><div><strong>舆策 · SENTRA</strong><span>详细分析 · 舆情 / 资金 / 候选股票全量视图</span></div></div>
        <nav className="main-nav" aria-label="主导航">
          <Link href="/">首页</Link>
          <Link href="/analysis" className="active">详细分析</Link>
          <Link href="/portfolio">策略与回测</Link>
          <Link href="/admin">系统管理</Link>
        </nav>
        <div className="system-status engine-switch">
          <span className={`status-dot ${sentra.apiOnline ? "" : "offline"}`} />
          <small>阶段：{data.stage} · API {sentra.apiOnline ? "在线" : "离线"}</small>
        </div>
      </header>

      <nav className="sub-nav" aria-label="详细分析子导航">
        {SUB_TABS.map(({ key, label }) => <button type="button" key={key} className={sub === key ? "active" : ""} onClick={() => setSub(key)}>{label}</button>)}
      </nav>

      {sub === "trends" && <section className="hotspot-center" aria-label="热点趋势中心">
        <div className="hotspot-heading"><div><span className="eyebrow">MOMENTUM & OUTBREAK</span><h2>热点趋势中心</h2><p>变化速度优先于绝对热度；默认隐藏无增长项目，只保留可执行的趋势信号。</p></div><div className={`hotspot-baseline ${burstRadar?.ready ? "ready" : "waiting"}`}><span>{burstRadar?.ready ? "周期基线可用" : "基线建立中"}</span><b>{industryTrends.length}<small> 个分析快照</small></b></div></div>
        <div className="hotspot-attention"><div className="attention-title"><span>需要关注</span><b>{attentionChanges.length}</b></div>{attentionChanges.map((item) => <article className={item.tone} key={item.title}><i /><div><b>{item.title}</b><small>{item.detail}</small></div></article>)}{!attentionChanges.length && <p>当前没有达到关注阈值的趋势变化</p>}</div>
        <div className="hotspot-toolbar"><nav aria-label="热点趋势页签"><button className={hotspotTab === "industries" ? "active" : ""} onClick={() => { setHotspotTab("industries"); setHotspotExpanded(false); }}>行业趋势<span>{industryTrends.length}</span></button><button className={hotspotTab === "keywords" ? "active" : ""} onClick={() => { setHotspotTab("keywords"); setHotspotExpanded(false); }}>爆发关键词<span>{activeKeywords.length}</span></button><button className={hotspotTab === "news" ? "active" : ""} onClick={() => { setHotspotTab("news"); setHotspotExpanded(false); }}>新闻增量<span>{newsIncrements.length}</span></button></nav><button className="hotspot-expand" onClick={() => setHotspotExpanded((value) => !value)}>{hotspotExpanded ? "收起" : "查看更多"}</button></div>
        {hotspotTab === "industries" && <div className="trend-table-wrap"><table className="trend-table compact"><thead><tr><th>当前</th><th>行业 / 标签</th><th>24H变化</th><th>近5次排名</th><th>热度 / 政策 / 情绪</th><th>持续时间</th></tr></thead><tbody>{risingIndustries.slice(0, hotspotExpanded ? 9 : 5).map((item) => <tr key={item.industry}><td><strong className="trend-rank">{String(item.current_rank).padStart(2, "0")}</strong></td><td><b>{item.industry}</b><div className="trend-tags">{item.tags.map((tag) => <span className={tag.includes("降温") || tag.includes("回落") ? "cooling" : tag.includes("爆发") || tag.includes("升温") ? "warming" : ""} key={tag}>{tag}</span>)}</div></td><td><div className={`trend-delta ${item.score_change_24h > 0 ? "up" : item.score_change_24h < 0 ? "down" : "flat"}`}><b>{item.score_change_24h > 0 ? "+" : ""}{item.score_change_24h}</b><small>排名 {item.rank_change_24h > 0 ? `↑${item.rank_change_24h}` : item.rank_change_24h < 0 ? `↓${Math.abs(item.rank_change_24h)}` : "—"}</small></div></td><td><div className="rank-history">{item.rank_history.map((rank, index) => <span key={`${rank}-${index}`}>{rank}</span>)}</div></td><td><TrendLines points={item.points} /></td><td><b className="persistence">{item.persistence_hours < 1 ? "<1小时" : `${item.persistence_hours}小时`}</b><small className="trend-sub">样本内持续</small></td></tr>)}{!industryTrends.length && <tr><td colSpan={6}><div className="trend-empty">完成至少两次分析后计算行业趋势。</div></td></tr>}</tbody></table></div>}
        {hotspotTab === "keywords" && <BurstTable title="有效爆发关键词" items={activeKeywords.slice(0, hotspotExpanded ? activeKeywords.length : 5)} ready={Boolean(burstRadar?.ready)} compact />}
        {hotspotTab === "news" && <BurstTable title="新闻数量增长" items={newsIncrements.slice(0, hotspotExpanded ? newsIncrements.length : 5)} ready={Boolean(burstRadar?.ready)} compact />}
        <p className="hotspot-note">增长率来自最近两次周期采集；无增长关键词默认隐藏。首次发现时间来自本机持久化历史。</p>
      </section>}

      {sub === "sentiment" && <section className="sentiment-panel-detail" aria-label="行业情绪面板">
        <div className="hotspot-heading"><div><span className="eyebrow">INDUSTRY SENTIMENT</span><h2>行业情绪面板</h2><p>展示各行业情绪方向、情绪分、驱动因素与风险因子。</p></div><div className="hotspot-baseline ready"><span>样本数</span><b>{sentiments.length}<small> 个行业</small></b></div></div>
        <div className="sentiment-score-overview"><div className="gauge"><span>{averageSentiment}</span><small>整体情绪方向分</small></div><div className="sentiment-copy"><b>{averageSentiment >= 61 ? "整体情绪偏积极" : averageSentiment <= 39 ? "整体情绪偏消极" : "整体情绪中性"}</b><p>{sentiments[0]?.sentiment_drivers?.[0] || "等待行业情绪 Agent 生成真实分析结果。"}</p></div></div>
        <div className="stock-pool-table"><table><thead><tr><th>行业</th><th>情绪方向</th><th>情绪分</th><th>驱动因素</th><th>风险因子</th></tr></thead><tbody>{sentiments.map((item) => <tr key={item.industry}><td><b>{item.industry}</b></td><td><span className={"candidate-risk risk-" + (item.sentiment === "positive" ? "low" : item.sentiment === "negative" ? "high" : "medium")}>{item.sentiment === "positive" ? "积极" : item.sentiment === "negative" ? "消极" : "中性"}</span></td><td><strong>{item.sentiment_score}</strong></td><td><ul>{item.sentiment_drivers.map((d) => <li key={d}>{d}</li>)}</ul></td><td><div className="keyword-cloud">{item.risk_factors.map((r) => <span className="risk" key={r}>{r}</span>)}{!item.risk_factors.length && <span>暂无</span>}</div></td></tr>)}</tbody></table></div>
        {!sentiments.length && <div className="trust-empty">运行分析后显示行业情绪数据。</div>}
      </section>}

      {sub === "capital" && <section className="capital-panel-detail" aria-label="资金流面板">
        <div className="hotspot-heading"><div><span className="eyebrow">CAPITAL FLOW</span><h2>资金流面板</h2><p>展示各行业研报评级、资金流向与重点资金股。</p></div><div className={"quadrant-mode " + (data.research_capital_metadata?.data_mode || "unknown")}><span>资金数据</span><b>{data.research_capital_metadata?.data_mode === "real" ? "真实" : data.research_capital_metadata?.data_mode === "simulated" ? "模拟" : "待接入"}</b></div></div>
        {data.research_capital_metadata?.warning && <div className="notice-bar"><span>i</span>{data.research_capital_metadata.warning}</div>}
        <div className="stock-pool-table"><table><thead><tr><th>行业</th><th>研报评级</th><th>今日资金</th><th>5日资金</th><th>10日资金</th><th>重点资金股</th></tr></thead><tbody>{capital.map((item) => <tr key={item.industry}><td><b>{item.industry}</b></td><td><strong>{item.research_rating}</strong></td><td><b>{item.capital_flow.today}</b></td><td><b>{item.capital_flow.five_days}</b></td><td><b>{item.capital_flow.ten_days}</b></td><td><div className="keyword-cloud">{item.top_capital_stocks.map((s) => <span key={s}>{s}</span>)}</div></td></tr>)}</tbody></table></div>
        {!capital.length && <div className="trust-empty">运行资金整合节点后显示资金流数据。</div>}
      </section>}

      {sub === "quadrant" && <><section className="quadrant-panel" aria-label="行业四象限图">
        <div className="quadrant-heading"><div><span className="eyebrow">CAPITAL × SENTIMENT MATRIX</span><h2>行业四象限图</h2><p>横轴资金强弱，纵轴舆情强弱；气泡大小代表综合热度，颜色代表情绪方向。</p></div><div className={`quadrant-mode ${quadrant?.capital_data_mode || "unknown"}`}><span>资金数据</span><b>{quadrant?.capital_data_mode === "real" ? "真实" : quadrant?.capital_data_mode === "simulated" ? "模拟" : "待接入"}</b></div></div>
        <div className="quadrant-layout"><div className="quadrant-chart"><span className="axis-y">舆情强弱 ↑</span><span className="axis-x">资金强弱 →</span><div className="quadrant-label q1"><b>舆情强 · 资金弱</b><small>可能炒作</small></div><div className="quadrant-label q2"><b>舆情强 · 资金强</b><small>重点观察</small></div><div className="quadrant-label q3"><b>舆情弱 · 资金弱</b><small>低优先级</small></div><div className="quadrant-label q4"><b>舆情弱 · 资金强</b><small>资金先行</small></div><i className="midline vertical" style={{ left: `${quadrant?.threshold || 60}%` }} /><i className="midline horizontal" style={{ bottom: `${quadrant?.threshold || 60}%` }} />{quadrant?.points?.map((point) => { const size = 24 + point.combined_heat * 0.32; return <button className={`quadrant-bubble ${point.sentiment} ${selectedEvent ? "event-dim" : ""}`} style={{ left: `${point.capital_score}%`, bottom: `${point.public_opinion_score}%`, width: `${size}px`, height: `${size}px` }} title={`${point.industry}｜资金 ${point.capital_score}｜舆情 ${point.public_opinion_score}｜${point.quadrant}`} key={point.industry}><span>{point.industry}</span><small>{point.combined_heat}</small></button>; })}</div><aside className="quadrant-side"><div className="quadrant-legend"><h3>气泡图例</h3><span className="positive">积极情绪</span><span className="neutral">中性情绪</span><span className="negative">消极情绪</span><small>气泡越大，综合热度越高</small></div><div className="quadrant-rank"><h3>象限归类</h3>{["重点观察", "可能炒作", "资金先行", "低优先级"].map((group) => <div key={group}><span>{group}</span><b>{quadrant?.points?.filter((item) => item.quadrant === group).map((item) => item.industry).join("、") || "暂无"}</b></div>)}</div></aside></div>
        <div className="quadrant-formula"><span>{quadrant?.axis_formula?.capital || "资金轴等待数据"}</span><span>{quadrant?.axis_formula?.public_opinion || "舆情轴等待数据"}</span><span>强弱阈值：{quadrant?.threshold || 60} 分</span></div>
      </section>

      <section className="divergence-panel" aria-label="舆情资金背离监控">
        <div className="divergence-heading"><div><span className="eyebrow">SENTIMENT × CAPITAL DIVERGENCE</span><h2>舆情—资金背离监控</h2><p>优先捕捉舆情、资金、政策、新闻和股票候选之间的不一致。</p></div><div className={`divergence-count ${divergence?.high_count ? "danger" : ""}`}><span>当前背离 / 高风险</span><b>{divergence?.alert_count || 0}<small> / {divergence?.high_count || 0}</small></b></div></div>
        <div className="divergence-readiness"><span className={divergence?.trend_baseline_ready ? "ready" : "waiting"}>趋势基线：{divergence?.trend_baseline_ready ? "可用" : "等待周期样本"}</span><span className={divergence?.news_baseline_ready ? "ready" : "waiting"}>新闻增量基线：{divergence?.news_baseline_ready ? "可用" : "等待周期采集"}</span><span className={divergence?.capital_data_mode === "real" ? "ready" : "simulated"}>资金流：{divergence?.capital_data_mode === "real" ? "真实" : divergence?.capital_data_mode === "simulated" ? "模拟" : "待接入"}</span></div>
        <div className="divergence-layout"><div className="divergence-alerts">{divergence?.alerts?.map((item, index) => <article className={item.severity} key={`${item.industry}-${item.type}-${index}`}><div className="divergence-alert-head"><span>{item.type}</span><em>{item.severity === "high" ? "高风险" : item.severity === "medium" ? "需关注" : "观察"}</em></div><h3>{item.industry}<small>热度 {item.industry_heat}</small></h3><p>{item.evidence}</p><div className="divergence-sources">{item.sources.map((source) => <span key={source}>{source}</span>)}</div><footer><b>执行提示</b>{item.action}</footer></article>)}{!divergence?.alerts?.length && <div className="divergence-empty"><b>暂未触发背离</b><p>{divergence?.available ? "当前指标之间未达到背离阈值；继续通过周期采集观察变化。" : "完成分析与资金整合后开始监控。"}</p></div>}</div><aside className="divergence-rules"><h3>背离规则状态</h3>{divergence?.rules?.map((rule) => <div key={rule.type}><span>{rule.type}</span><small>{rule.threshold}</small><em className={rule.requires_history && !(rule.type.includes("新闻") ? divergence.news_baseline_ready : divergence.trend_baseline_ready) ? "waiting" : "active"}>{rule.requires_history ? "周期规则" : "即时规则"}</em></div>)}</aside></div>
        <p className="divergence-note">{divergence?.message || "背离仅作为复核提示，不构成自动交易信号。"}</p>
      </section></>}

      {sub === "timeline" && <section className="event-timeline-panel" aria-label="新闻与事件时间轴">
        <div className="event-timeline-heading"><div><span className="eyebrow">NEWS & EVENT TIMELINE</span><h2>新闻与事件时间轴</h2><p>按时间整合财经资讯与股吧热点；点击事件联动高亮影响行业和股票。</p></div><div className="event-total"><span>事件总量</span><b>{eventTimeline?.events?.length || 0}</b></div></div>
        <div className="event-filter-stack"><div className="event-source-filters"><span>来源</span>{(["全部来源", "财经资讯", "股吧话题"] as const).map((source) => <button className={eventSource === source ? "active" : ""} onClick={() => setEventSource(source)} key={source}>{source}<small>{eventSourceCount(source)}</small></button>)}</div><div className="event-filters"><span>类型</span>{["全部", ...(eventTimeline?.categories || [])].map((category) => <button className={eventCategory === category ? "active" : ""} onClick={() => setEventCategory(category)} key={category}>{category}<small>{category === "全部" ? eventTimeline?.events?.length || 0 : eventTimeline?.category_counts?.[category] || 0}</small></button>)}</div></div>
        <div className="event-timeline-layout"><div className="event-stream">{visibleEvents.map((item) => <button className={`event-row category-${item.category} ${selectedEvent?.id === item.id ? "active" : ""}`} onClick={() => setSelectedEvent(selectedEvent?.id === item.id ? null : item)} key={item.id}><time>{new Date(item.timestamp).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })}</time><i /><div><span className="event-category">{item.category}</span><h3>{item.title}</h3><small>{item.source} · 影响 {item.affected_industries.length} 个行业 / {item.affected_stocks.length} 只股票</small></div><em>{selectedEvent?.id === item.id ? "已高亮" : "查看影响"}</em></button>)}{!visibleEvents.length && <div className="event-empty">当前分类暂无事件</div>}</div><aside className="event-impact"><div className="event-impact-head"><span>EVENT IMPACT</span><h3>{selectedEvent?.title || "选择事件查看影响"}</h3>{selectedEvent && <button onClick={() => setSelectedEvent(null)}>清除高亮</button>}</div>{selectedEvent ? <><p>{selectedEvent.summary || "该事件没有正文摘要。"}</p><div className="impact-group"><span>影响行业</span><div>{selectedEvent.affected_industries.map((industry) => <span key={industry}>{industry}</span>)}{!selectedEvent.affected_industries.length && <small>未匹配行业</small>}</div></div><div className="impact-group"><span>影响股票</span><div>{selectedEvent.affected_stocks.map((stock) => <span key={stock}>{stock}</span>)}{!selectedEvent.affected_stocks.length && <small>未匹配股票</small>}</div></div><div className="impact-group"><span>命中关键词</span><div>{selectedEvent.matched_keywords.map((word) => <em key={word}>{word}</em>)}</div></div>{selectedEvent.url && <a className="event-source-link" href={selectedEvent.url} target="_blank" rel="noreferrer">查看原始资讯 ↗</a>}</> : <div className="impact-placeholder">点击左侧任意事件，行业四象限气泡和个股候选池将同步突出显示。</div>}</aside></div>
        <p className="event-timeline-note">{eventTimeline?.message || "采集资讯后生成事件时间轴。"}</p>
      </section>}

      {sub === "stocks" && <section className="stock-pool" aria-label="个股候选池">
        <div className="stock-pool-heading"><div><span className="eyebrow">STOCK CANDIDATE UNIVERSE</span><h2>个股候选池</h2><p>覆盖资金节点输出的全部股票；策略入选股使用交易计划，未入选股只展示规则观察区间。</p></div><div className={`stock-data-mode ${stockPool?.market_data_mode || "unknown"}`}><span>行情数据</span><b>{stockPool?.market_data_mode === "real" ? "真实" : stockPool?.market_data_mode === "simulated" ? "模拟" : "待接入"}</b></div></div>
        <div className="stock-pool-toolbar"><div><span>候选股票</span><b>{stockPool?.stock_count || 0}</b><small>只</small></div><nav aria-label="候选池排序"><span>排序：</span><button className={stockSort === "composite" ? "active" : ""} onClick={() => setStockSort("composite")}>综合分</button><button className={stockSort === "capital" ? "active" : ""} onClick={() => setStockSort("capital")}>资金排名</button><button className={stockSort === "heat" ? "active" : ""} onClick={() => setStockSort("heat")}>行业热度</button><button className={stockSort === "risk" ? "active" : ""} onClick={() => setStockSort("risk")}>风险从低到高</button></nav></div>
        <div className="stock-pool-table"><table><thead><tr><th>股票 / 行业</th><th>综合分</th><th>舆情关联</th><th>资金排名</th><th>当前价格 / 5日涨跌</th><th>波动率</th><th>买入区间</th><th>止损价</th><th>目标区间</th><th>风险</th><th>入选原因</th></tr></thead><tbody>{sortedStocks.map((item) => <tr className={`${item.selected ? "selected" : ""}`} key={`${item.industry}-${item.stock}`}><td><b>{item.stock}</b><small>{item.industry} · {item.selected ? "本次入选" : "观察候选"}</small></td><td><strong className="candidate-score">{item.composite_score}</strong><small>热度 {item.industry_heat}</small></td><td><b>{item.association_count} 次</b><div className="topic-popover">{item.hot_topics.slice(0, 2).map((topic) => topic.url ? <a href={topic.url} target="_blank" rel="noreferrer" key={topic.url}>{topic.title}</a> : <span key={topic.title}>{topic.title}</span>)}{!item.hot_topics.length && <span>暂无直接话题关联</span>}</div></td><td><strong>#{item.capital_rank}</strong></td><td><b>¥{item.current_price.toFixed(2)}</b><small className={item.five_day_change_pct >= 0 ? "price-up" : "price-down"}>{item.five_day_change_pct >= 0 ? "+" : ""}{item.five_day_change_pct}%</small></td><td><b>{item.volatility_pct}%</b></td><td><b>¥{item.buy_range[0]}–{item.buy_range[1]}</b><small>{item.price_plan_type}</small></td><td><strong className="stop-price">¥{item.stop_price}</strong></td><td><b>¥{item.target_range[0]}–{item.target_range[1]}</b></td><td><span className={`candidate-risk risk-${item.risk_level}`}>{item.risk_level}</span><small>{item.risk_score}</small></td><td><ul>{item.selection_reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul></td></tr>)}{!sortedStocks.length && <tr><td colSpan={11}><div className="stock-pool-empty">完成资金整合和策略报告后生成个股候选池</div></td></tr>}</tbody></table></div>
        <p className="stock-pool-note">{stockPool?.message || "候选池等待策略工作流运行。"}</p>
      </section>}

      {sub === "sources" && <section className="sources-panel" aria-label="数据来源面板">
        <div className="hotspot-heading"><div><span className="eyebrow">DATA SOURCES</span><h2>数据来源</h2><p>展示当前采集的原始数据来源，包括股吧热门话题与财经文章。</p></div><div className="hotspot-baseline ready"><span>采集量</span><b>{(data.collection_summary?.guba_topic_count || 0) + (data.collection_summary?.finance_article_count || 0)}<small> 条</small></b></div></div>
        <div className="opportunity-layout">
          <div className="opportunity-quadrant">
            <PanelTitle eyebrow="GUBA TOPICS" title="股吧热门话题" action={isDemo ? "DEMO" : "LIVE"} />
            <div className="topic-list">{topics.map((topic, index) => <div className="topic-item" key={`src-${topic.title}-${index}`}><span className="topic-rank">{String(topic.rank || index + 1).padStart(2, "0")}</span><div><b>{topic.title}</b><small>阅读 {compactNumber(topic.read_count || 0)} | 评论 {compactNumber(topic.comment_count || 0)} | 关联 {topic.stocks?.length || 0} 项</small>{(topic.stocks?.length ?? 0) > 0 && <div className="keyword-cloud">{(topic.stocks || []).map((s) => <span key={s.code}>{s.name} ({s.code})</span>)}</div>}</div></div>)}</div>
          </div>
          <aside className="opportunity-rank">
            <PanelTitle eyebrow="FINANCE ARTICLES" title="财经文章" action={articles.length + " ARTICLES"} />
            <div className="flow-list">{articles.map((item) => <div key={item.url}><span><b>{item.title}</b><small>{item.time?.slice(11, 16) || "--:--"}</small></span><em>{item.url ? <a href={item.url} target="_blank" rel="noreferrer">查看原文</a> : "无链接"}</em></div>)}{!articles.length && <p className="empty-copy">等待采集财经文章数据。</p>}</div>
          </aside>
        </div>
        {!topics.length && !articles.length && <div className="trust-empty">运行研判后显示原始数据来源。</div>}
      </section>}
    </main>
  );
}

function TrendLines({ points }: { points: TrendPoint[] }) {
  if (!points?.length) return <span className="trend-empty">—</span>;
  const max = Math.max(...points.map((p) => p.combined_score), 1);
  return (
    <svg viewBox="0 0 120 36" className="trend-spark">
      <polyline fill="none" stroke="currentColor" strokeWidth="1.5" points={points.map((p, i) => `${(i / Math.max(points.length - 1, 1)) * 120},${36 - (p.combined_score / max) * 30}`).join(" ")} />
    </svg>
  );
}

function BurstTable({ title, items, ready, compact }: { title: string; items: BurstItem[]; ready: boolean; compact: boolean }) {
  return (
    <div className="burst-table-wrap">
      <h3 className="burst-title">{title}<small>{ready ? "基线已建立" : "等待周期基线"}</small></h3>
      <div className="burst-grid">
        {items.map((item) => (
          <article className={`burst-card ${item.is_new ? "new" : ""}`} key={`${item.type}-${item.name}-${item.first_seen_at}`}>
            <header><b>{item.name}</b><span>{item.type === "keyword" ? "关键词" : item.type === "industry" ? "行业" : "话题"}</span></header>
            <ul>
              <li><span>1H 讨论</span><b>{item.discussion_delta_1h == null ? "—" : `+${item.discussion_delta_1h}`}</b></li>
              <li><span>阅读增速</span><b>{item.read_growth_rate == null ? "—" : `${item.read_growth_rate.toFixed(1)}%`}</b></li>
              <li><span>评论增速</span><b>{item.comment_growth_rate == null ? "—" : `${item.comment_growth_rate.toFixed(1)}%`}</b></li>
              <li><span>新闻增速</span><b>{item.news_growth_rate == null ? "—" : `${item.news_growth_rate.toFixed(1)}%`}</b></li>
            </ul>
            <footer><span>{item.source}</span><em>{item.is_new ? "首次出现" : "持续"}</em></footer>
          </article>
        ))}
        {!items.length && <p className="empty-copy">无有效{compact ? "增长项" : "爆发信号"}</p>}
      </div>
    </div>
  );
}