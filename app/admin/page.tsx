"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import "./admin.css";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
type Source = { key: string; name: string; mode: string; source: string; record_count?: number; success_rate?: number; missing_rate: number; freshness: string; age_minutes?: number; last_failure?: string };
type NodeLog = { id: number; node_id: string; node_name: string; status: string; mode: string; started_at: string; duration_ms?: number; input_count: number; output_count: number; retry_count: number; error?: string };
type Node = { id: string; name: string; status: string; mode: string; started_at: string; ended_at?: string; duration_ms?: number; input_count: number; output_count: number; retry_count: number; run_count: number; error?: string };
type Batch = { id: number; captured_at: string; guba_count: number; article_count: number; status: string };
type Topic = { title: string; url?: string; read_count?: number; comment_count?: number; stocks?: { name: string; code: string }[] };
type Article = { title: string; url: string; time: string; content?: string };
type MarketLayer = { scope: string; name: string; count_label: string; target_count: number; mapped_count: number; description: string; frequency: string; default_types: string[]; raw_related_count?: number; filtered_count?: number };
type MarketRun = { scope: string; status: string; source: string; methodology: string; completed_at: string; duration_ms: number; target_count: number | "all"; quote_count: number; capital_count: number; note: string };
type MarketCenter = { provider: string; provider_type: string; auto_fetch: boolean; data_mode: string; workflow_mode?: string; methodology: string; warning: string; layers: MarketLayer[]; last_run?: MarketRun | null };
type AdminData = { updated_at?: string; stage: string; last_error?: string; database_path: string; database_size_bytes: number; journal_mode: string; read_only_console: boolean; data_trust?: { overall_level: string; sources: Source[] }; persistence_status?: { engine: string; schema_version: number; database_file: string; last_persisted_at: string; counts: Record<string, number> }; scheduler_status?: { enabled: boolean; running: boolean; next_run?: { name: string; planned_at: string } | null; today?: { full_runs: number; news_checks: number; skipped: number }; jobs?: { id: string; name: string; schedule: string; action: string }[]; recent_runs?: { id: number; job_id: string; status: string; started_at: string; error?: string; detail?: { reason?: string } }[]; limits?: Record<string, number | boolean>; calendar_note?: string }; workflow_nodes?: Node[]; recent_batches?: Batch[]; recent_node_logs?: NodeLog[]; guba_topics?: Topic[]; finance_commentary?: Article[]; market_data_center?: MarketCenter };

const nav = [["overview", "运行总览"], ["market-data", "行情资金"], ["sources", "来源质量"], ["database", "数据库"], ["workflow", "节点日志"], ["scheduler", "定时任务"], ["raw", "原始数据"]];
const statusText: Record<string, string> = { success: "成功", failed: "失败", running: "运行中", waiting: "等待", skipped: "跳过" };
const bytes = (value = 0) => value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(2)} MB`;
const dateText = (value?: string) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";

export default function AdminPage() {
  const [data, setData] = useState<AdminData | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [rawType, setRawType] = useState<"topics" | "articles">("topics");
  const [marketBusy, setMarketBusy] = useState("");
  const [marketNotice, setMarketNotice] = useState("");

  async function load() {
    try {
      const response = await fetch(`${API_BASE}/api/admin/overview`);
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || "后台数据读取失败");
      setData(payload.data); setError("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }
  useEffect(() => { const initial = window.setTimeout(load, 0); const timer = window.setInterval(load, 15000); return () => { window.clearTimeout(initial); window.clearInterval(timer); }; }, []);

  async function toggleScheduler() {
    setBusy(true);
    try {
      await fetch(`${API_BASE}/api/scheduler/${data?.scheduler_status?.enabled ? "disable" : "enable"}`, { method: "POST" });
      await load();
    } finally { setBusy(false); }
  }

  async function fetchMarketData(scope: string, types: string[]) {
    const task = `${scope}:${types.join(",")}`;
    setMarketBusy(task); setMarketNotice("");
    try {
      const response = await fetch(`${API_BASE}/api/market-data/fetch?scope=${encodeURIComponent(scope)}&types=${encodeURIComponent(types.join(","))}`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || "数据获取失败");
      setMarketNotice(`获取完成：行情 ${payload.data.quote_count} 条，资金流 ${payload.data.capital_count} 条`);
      await load();
    } catch (reason) { setMarketNotice(reason instanceof Error ? reason.message : String(reason)); }
    finally { setMarketBusy(""); }
  }

  const failures = useMemo(() => (data?.recent_node_logs || []).filter((item) => item.status === "failed" || item.error), [data]);
  const visibleRaw = useMemo(() => {
    const rows = rawType === "topics" ? data?.guba_topics || [] : data?.finance_commentary || [];
    return rows.filter((item) => `${item.title} ${"content" in item ? item.content || "" : ""}`.toLowerCase().includes(query.toLowerCase()));
  }, [data, query, rawType]);

  return <main className="admin-shell">
    <aside className="admin-sidebar"><Link className="admin-brand" href="/"><span>S</span><div><b>舆策 · SENTRA</b><small>后台运维管理</small></div></Link><nav>{nav.map(([id, label]) => <a href={`#${id}`} key={id}>{label}<span>›</span></a>)}</nav><div className="admin-safety"><b>安全模式</b><p>只读数据库视图；不开放任意 SQL 和直接删除。</p></div><Link className="back-dashboard" href="/">← 返回决策大屏</Link></aside>
    <div className="admin-main">
      <header className="admin-header"><div><span>OPERATIONS CONSOLE</span><h1>系统运维与数据管理</h1><p>来源、数据库、工作流与采集调度统一观测</p></div><div className="admin-live"><i className={error ? "error" : ""} /><span>{error ? "API 连接异常" : "系统在线"}</span><small>{dateText(data?.updated_at)}</small></div></header>
      {error && <div className="admin-error">{error}<button onClick={load}>重新连接</button></div>}

      <section id="overview" className="admin-section"><SectionHead eyebrow="SYSTEM OVERVIEW" title="运行总览" note="15秒自动刷新" /><div className="admin-kpis"><Kpi label="数据库" value={data?.persistence_status?.engine || "—"} note={`Schema v${data?.persistence_status?.schema_version || "—"}`} /><Kpi label="数据库体积" value={bytes(data?.database_size_bytes)} note={`Journal ${data?.journal_mode || "—"}`} /><Kpi label="采集批次" value={`${data?.persistence_status?.counts?.collection_batches || 0}`} note={`原始记录 ${(data?.persistence_status?.counts?.raw_topics || 0) + (data?.persistence_status?.counts?.raw_articles || 0)}`} /><Kpi label="节点日志" value={`${data?.persistence_status?.counts?.node_execution_logs || 0}`} note={`${failures.length} 条近期失败`} tone={failures.length ? "warn" : "good"} /><Kpi label="来源可信度" value={data?.data_trust?.overall_level === "good" ? "可信可用" : "需要关注"} note={`${data?.data_trust?.sources?.length || 0} 个数据来源`} /><Kpi label="定时调度" value={data?.scheduler_status?.enabled ? "已启用" : "已暂停"} note={data?.scheduler_status?.next_run ? `下次 ${dateText(data.scheduler_status.next_run.planned_at)}` : "暂无下次任务"} tone={data?.scheduler_status?.enabled ? "good" : "warn"} /></div></section>

      <section id="market-data" className="admin-section market-data-center"><SectionHead eyebrow="ON-DEMAND MARKET DATA" title="行情与资金数据中心" note="默认不采集 · 按钮触发后才访问东方财富" />
        <div className="market-provider-strip"><div><span>数据提供方</span><b>{data?.market_data_center?.provider || "东方财富公开页面接口"}</b><small>{data?.market_data_center?.methodology || "东方财富口径"}</small></div><div><span>自动采集</span><b className="off">关闭</b><small>页面轮询只读取状态，不请求外部数据</small></div><div><span>上次手动获取</span><b>{data?.market_data_center?.last_run ? dateText(data.market_data_center.last_run.completed_at) : "尚未获取"}</b><small>{data?.market_data_center?.last_run ? `行情 ${data.market_data_center.last_run.quote_count} · 资金 ${data.market_data_center.last_run.capital_count}` : "点击下方按钮开始"}</small></div></div>
        <div className="market-layer-grid">{data?.market_data_center?.layers?.map((layer, index) => <article key={layer.scope}><header><span>0{index + 1}</span><div><b>{layer.name}</b><small>{layer.count_label} · 代码映射 {layer.mapped_count}/{layer.target_count}{layer.raw_related_count ? ` · 话题标的 ${layer.raw_related_count}` : ""}{layer.filtered_count ? ` · 已过滤 ${layer.filtered_count}` : ""}</small></div></header><p>{layer.description}</p>{layer.scope === "related" && layer.raw_related_count ? <p className="layer-hint">股吧话题共 {layer.raw_related_count} 条标的，过滤掉指数 / 海外品种 / 非 6 位 code 后剩 {layer.target_count} 条；东方财富公开接口单次最多返回 100 行（按活跃度排序），因此实际可拉到 ≤100 条行情。</p> : null}<dl><div><dt>建议频率</dt><dd>{layer.frequency}</dd></div><div><dt>默认内容</dt><dd>{layer.default_types.includes("capital") ? "行情 + 资金流" : "轻量行情"}</dd></div></dl><footer>{layer.scope === "market" ? <button disabled={Boolean(marketBusy)} onClick={() => fetchMarketData(layer.scope, ["quotes"])}>{marketBusy === `${layer.scope}:quotes` ? "正在获取…" : "获取全市场轻量行情"}</button> : <><button disabled={Boolean(marketBusy) || layer.target_count === 0} onClick={() => fetchMarketData(layer.scope, ["quotes"])}>{marketBusy === `${layer.scope}:quotes` ? "正在获取…" : "仅获取行情"}</button><button className="primary" disabled={Boolean(marketBusy) || layer.target_count === 0} onClick={() => fetchMarketData(layer.scope, ["quotes", "capital"])}>{marketBusy === `${layer.scope}:quotes,capital` ? "正在获取…" : "获取行情 + 资金流"}</button></>}</footer></article>)}</div>
        <div className="market-data-note"><span>{marketNotice || data?.market_data_center?.warning || "页面加载不会自动访问外部数据源。"}</span><b>{data?.market_data_center?.workflow_mode === "real" ? "已应用到策略工作流，当前策略使用真实行情与资金流。" : "当前采集结果仅进入隔离缓存，尚不会替换策略中的模拟数据。"}</b></div>
      </section>

      <section id="sources" className="admin-section"><SectionHead eyebrow="DATA PROVENANCE" title="来源质量" note="真实/模拟清晰标识" /><div className="source-admin-grid">{data?.data_trust?.sources?.map((source) => <article key={source.key}><div><b>{source.name}</b><span className={source.mode}>{source.mode === "real" ? "真实" : "模拟"}</span></div><p>{source.source}</p><dl><div><dt>记录数</dt><dd>{source.record_count ?? "模拟生成"}</dd></div><div><dt>成功率</dt><dd>{source.success_rate == null ? "不适用" : `${source.success_rate}%`}</dd></div><div><dt>缺失率</dt><dd>{source.missing_rate}%</dd></div><div><dt>新鲜度</dt><dd>{source.freshness}</dd></div></dl><footer className={source.last_failure ? "failed" : ""}>上次失败：{source.last_failure || "无"}</footer></article>)}</div></section>

      <section id="database" className="admin-section"><SectionHead eyebrow="SQLITE STORAGE" title="数据库与采集批次" note={data?.database_path || "sentra.sqlite3"} /><div className="db-layout"><div className="db-counts">{Object.entries(data?.persistence_status?.counts || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll("_", " ")}</span><b>{value}</b></div>)}</div><div className="admin-table"><table><thead><tr><th>批次</th><th>采集时间</th><th>股吧</th><th>文章</th><th>状态</th></tr></thead><tbody>{data?.recent_batches?.map((batch) => <tr key={batch.id}><td>#{batch.id}</td><td>{dateText(batch.captured_at)}</td><td>{batch.guba_count}</td><td>{batch.article_count}</td><td><Status value={batch.status} /></td></tr>)}</tbody></table></div></div></section>

      <section id="workflow" className="admin-section"><SectionHead eyebrow="PIPELINE LOGS" title="节点运行与失败记录" note="最近30条" /><div className="node-live-grid">{data?.workflow_nodes?.map((node) => <article key={node.id}><Status value={node.status} /><b>{node.name}</b><small>{node.mode || "待运行"} · {node.duration_ms == null ? "—" : `${node.duration_ms}ms`}</small><p>输入 {node.input_count} · 输出 {node.output_count} · 重试 {node.retry_count}</p></article>)}</div><div className="admin-table logs"><table><thead><tr><th>时间</th><th>节点</th><th>模式</th><th>状态</th><th>耗时</th><th>输入/输出</th><th>错误</th></tr></thead><tbody>{data?.recent_node_logs?.map((log) => <tr key={log.id}><td>{dateText(log.started_at)}</td><td>{log.node_name}</td><td>{log.mode}</td><td><Status value={log.status} /></td><td>{log.duration_ms == null ? "—" : `${log.duration_ms}ms`}</td><td>{log.input_count} / {log.output_count}</td><td className={log.error ? "log-error" : ""}>{log.error || "—"}</td></tr>)}</tbody></table></div></section>

      <section id="scheduler" className="admin-section"><SectionHead eyebrow="SCHEDULE CONTROL" title="定时采集管理" note={data?.scheduler_status?.calendar_note || "北京时间"} action={<button disabled={busy} onClick={toggleScheduler}>{data?.scheduler_status?.enabled ? "暂停调度" : "启用调度"}</button>} /><div className="scheduler-admin"><div className="job-grid">{data?.scheduler_status?.jobs?.map((job) => <article key={job.id}><i /><b>{job.name}</b><span>{job.schedule}</span><small>{job.action}</small></article>)}</div><aside><h3>今日执行</h3><div><span>全量运行</span><b>{data?.scheduler_status?.today?.full_runs || 0}</b></div><div><span>新闻检查</span><b>{data?.scheduler_status?.today?.news_checks || 0}</b></div><div><span>保护跳过</span><b>{data?.scheduler_status?.today?.skipped || 0}</b></div></aside></div></section>

      <section id="raw" className="admin-section"><SectionHead eyebrow="RAW DATA EXPLORER" title="当前原始数据" note="只读查看，原文可跳转" /><div className="raw-toolbar"><div><button className={rawType === "topics" ? "active" : ""} onClick={() => setRawType("topics")}>股吧话题 {data?.guba_topics?.length || 0}</button><button className={rawType === "articles" ? "active" : ""} onClick={() => setRawType("articles")}>财经文章 {data?.finance_commentary?.length || 0}</button></div><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题或正文关键词" /></div><div className="raw-list">{visibleRaw.map((row, index) => <article key={`${row.title}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><div><b>{row.title}</b>{rawType === "topics" ? <small>阅读 {Number((row as Topic).read_count || 0).toLocaleString()} · 评论 {Number((row as Topic).comment_count || 0).toLocaleString()} · 关联 {(row as Topic).stocks?.map((stock) => stock.name).join("、") || "无"}</small> : <small>{(row as Article).time || "发布时间未知"} · 正文 {((row as Article).content || "").length} 字</small>}</div>{row.url ? <a href={row.url} target="_blank" rel="noreferrer">原文 ↗</a> : <em>无链接</em>}</article>)}{!visibleRaw.length && <p>没有匹配的数据</p>}</div></section>
    </div>
  </main>;
}

function SectionHead({ eyebrow, title, note, action }: { eyebrow: string; title: string; note?: string; action?: React.ReactNode }) { return <div className="admin-section-head"><div><span>{eyebrow}</span><h2>{title}</h2></div><div>{note && <small>{note}</small>}{action}</div></div>; }
function Kpi({ label, value, note, tone = "" }: { label: string; value: string; note: string; tone?: string }) { return <article className={tone}><span>{label}</span><b>{value}</b><small>{note}</small></article>; }
function Status({ value }: { value: string }) { return <span className={`admin-status ${value}`}>{statusText[value] || value}</span>; }
