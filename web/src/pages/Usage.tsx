import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { UsageGroup, UsageSummary } from "../api/types";
import { useI18n } from "../i18n";

const nf = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

function number(value: number | null, source?: string) {
  if (value === null) return "–";
  return `${source === "ESTIMATED" ? "≈" : ""}${nf.format(value)}`;
}

function duration(value: number | null) {
  if (value === null) return "–";
  const seconds = Math.round(value / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function Usage() {
  const { lang } = useI18n();
  const [params, setParams] = useSearchParams();
  const days = Number(params.get("days") || 30);
  const runId = params.get("run") || undefined;
  const query = useQuery({
    queryKey: ["usage", days, runId], queryFn: () => api.usage(days, runId), refetchInterval: 4000,
  });
  const data = query.data;
  const zh = lang === "zh";
  if (query.isLoading) return <div className="page">{zh ? "正在读取真实用量…" : "Loading real usage…"}</div>;
  if (!data?.has_data) return <div className="page usage-page"><UsageHeader zh={zh} days={days} setDays={(value) => setParams({ days: String(value) })} /><section className="card usage-empty"><span className="usage-orb" /><h2>{zh ? "暂无 Token 数据" : "No token data yet"}</h2><p>{zh ? "开始一次真实模型任务后，这里会显示上下文与 Token 使用情况。" : "Run a real model task to see context and token usage here."}</p></section></div>;
  return <div className="page usage-page">
    <UsageHeader zh={zh} days={days} setDays={(value) => setParams({ days: String(value) })} />
    <div className="usage-top-grid"><ContextCard data={data} zh={zh} /><section className="card usage-metrics"><span className="eyebrow">Session Metrics · {data.usage_source}</span><h2>{zh ? "会话指标" : "Session metrics"}</h2><div className="metric-grid"><Metric label={zh ? "累计 Tokens" : "Total tokens"} value={number(data.total_tokens, data.usage_source)} /><Metric label={zh ? "模型请求" : "Model requests"} value={String(data.requests)} /><Metric label={zh ? "运行时间" : "Runtime"} value={duration(data.runtime_ms)} /><Metric label={zh ? "平均模型延迟" : "Average latency"} value={duration(data.average_latency_ms)} /><Metric label={zh ? "缓存命中率" : "Cache hit rate"} value={data.cache_hit_rate === null ? "–" : `${(data.cache_hit_rate * 100).toFixed(1)}%`} /><Metric label={zh ? "会话费用" : "Session cost"} value={data.cost_total === null ? (zh ? "不可用" : "Unavailable") : `${data.currency === "USD" ? "$" : ""}${data.cost_total.toFixed(4)}`} /></div>{data.last_compression && <p className="muted">{zh ? "最近压缩" : "Last compaction"}: {number(data.last_compression.before_tokens)} → {number(data.last_compression.after_tokens)} · {number(data.last_compression.freed_tokens)} {zh ? "已释放" : "freed"}</p>}</section></div>
    <Composition data={data} zh={zh} />
    <div className="usage-breakdowns"><Breakdown title={zh ? "按 Agent" : "By agent"} items={data.by_agent} /><Breakdown title={zh ? "按模型" : "By model"} items={data.by_model} /><Breakdown title={zh ? "按 Provider" : "By provider"} items={data.by_provider} /></div>
    <section className="card"><span className="eyebrow">Usage Timeline</span><h2>{zh ? "调用时间线" : "Usage timeline"}</h2><div className="usage-timeline">{data.timeline.map((item, index) => <div key={`${item.timestamp}-${index}`}><time>{new Date(item.timestamp).toLocaleTimeString()}</time><strong>{item.agent}</strong><span>{item.model}</span><b>{number(item.tokens, item.source)}</b><small>{item.source}</small></div>)}</div></section>
  </div>;
}

function UsageHeader({ zh, days, setDays }: { zh: boolean; days: number; setDays: (days: number) => void }) {
  return <header className="usage-header"><div><span className="eyebrow">Token & Context Observatory</span><h1>{zh ? "用量与上下文" : "Usage & Context"}</h1><p>{zh ? "所有数字均标明 Reported、Estimated 或 Unavailable。" : "Every value is identified as Reported, Estimated, or Unavailable."}</p></div><div className="usage-range">{[1, 7, 30, 90].map((value) => <button className={days === value ? "on" : ""} key={value} onClick={() => setDays(value)}>{value === 1 ? (zh ? "今天" : "Today") : `${value}D`}</button>)}</div></header>;
}

function ContextCard({ data, zh }: { data: UsageSummary; zh: boolean }) {
  const c = data.context; const pct = c.percentage === null ? null : Math.min(100, c.percentage * 100);
  return <section className={`card context-card context-${c.status.toLowerCase()}`}><div className="context-title"><div><span className="eyebrow">Context Window</span><h2>{zh ? "上下文窗口" : "Context window"}</h2></div><strong>{number(c.current_tokens, c.source)} / {number(c.limit)}</strong></div><div className="context-status"><span>{c.status.replaceAll("_", " ")}</span><b>{pct === null ? "–" : `${pct.toFixed(1)}%`}</b></div><div className="context-track"><i style={{ width: `${pct ?? 0}%` }} /><em style={{ left: `${c.compression_threshold * 100}%` }} /></div><div className="context-foot"><span>{zh ? "压缩阈值" : "Compression"} <b>{Math.round(c.compression_threshold * 100)}%</b></span><span>{zh ? "距压缩" : "Until compaction"} <b>{number(c.until_compression)}</b></span></div><small>{c.source}{c.model ? ` · ${c.model}` : ""}</small></section>;
}

function Composition({ data, zh }: { data: UsageSummary; zh: boolean }) {
  const parts = [{ key: "input", label: zh ? "提示词" : "Input", value: data.input_tokens }, { key: "output", label: zh ? "回复" : "Output", value: data.output_tokens }, { key: "reasoning", label: zh ? "推理" : "Reasoning", value: data.reasoning_tokens }, { key: "cached", label: zh ? "缓存（输入子集）" : "Cached (input subset)", value: data.cached_input_tokens }, { key: "other", label: zh ? "其他" : "Other", value: data.other_tokens }];
  const exclusive = (data.input_tokens || 0) + (data.output_tokens || 0) + (data.other_tokens || 0);
  return <section className="card composition-card"><span className="eyebrow">Token Composition</span><h2>{zh ? "Token 构成" : "Token composition"}</h2><div className="composition-bar">{parts.filter((part) => !["cached", "reasoning"].includes(part.key) && part.value !== null).map((part) => <i className={`part-${part.key}`} key={part.key} style={{ width: `${exclusive ? ((part.value || 0) / exclusive) * 100 : 0}%` }} />)}</div><div className="composition-details">{parts.map((part) => <div key={part.key}><span className={`dot part-${part.key}`} />{part.label}<strong>{number(part.value)}</strong></div>)}</div><p className="muted">{zh ? "缓存属于输入、推理属于输出；二者不会重复计入 Total。" : "Cached is a subset of input and reasoning of output; neither is double-counted in Total."}</p></section>;
}

function Breakdown({ title, items }: { title: string; items: UsageGroup[] }) { const max = Math.max(...items.map((item) => item.tokens), 1); return <section className="card usage-breakdown"><h2>{title}</h2>{items.map((item) => <div key={item.name}><span>{item.name}</span><i><em style={{ width: `${(item.tokens / max) * 100}%` }} /></i><strong>{number(item.tokens)}</strong><small>{item.requests} req</small></div>)}</section>; }
function Metric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
