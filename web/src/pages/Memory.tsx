import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Download, Search, ShieldCheck, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import type { MemoryProposal, MemoryRecord } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n";

type Tab = "all" | "project" | "preferences" | "episodic";

export function Memory() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const memories = useQuery({ queryKey: ["memory"], queryFn: () => api.memories() });
  const search = useQuery({
    queryKey: ["memory-search", query],
    queryFn: () => api.memorySearch(query),
    enabled: Boolean(query.trim()),
  });
  const proposals = useQuery({ queryKey: ["memory-proposals"], queryFn: api.memoryProposals });
  const settings = useQuery({ queryKey: ["memory-settings"], queryFn: api.memorySettings });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["memory"] });
    qc.invalidateQueries({ queryKey: ["memory-proposals"] });
  };
  const action = useMutation({
    mutationFn: async (payload: { kind: "confirm" | "reject" | "forget"; id: string }) => {
      if (payload.kind === "confirm") return api.confirmMemory(payload.id);
      if (payload.kind === "reject") return api.rejectMemory(payload.id);
      return api.forgetMemory(payload.id);
    },
    onSuccess: invalidate,
  });
  const saveSettings = useMutation({
    mutationFn: api.saveMemorySettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memory-settings"] }),
  });
  const all = memories.data?.memories ?? [];
  const searchable = query.trim() ? (search.data?.memories ?? []) : all;
  const filtered = useMemo(() => searchable.filter((item) => {
    const tabMatch = tab === "all"
      || (tab === "project" && item.memory_type === "project")
      || (tab === "preferences" && ["semantic_user", "procedural_preference"].includes(item.memory_type))
      || (tab === "episodic" && item.memory_type === "episodic");
    return tabMatch;
  }), [searchable, tab]);
  const active = all.filter((item) => item.status === "active").length;
  const projects = new Set(all.map((item) => item.project_id).filter(Boolean)).size;

  const exportData = async () => {
    const data = await api.exportMemory();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "ai-team-os-memory.json";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="page memory-page">
      <div className="page-heading">
        <div><span className="eyebrow">M4-A · Controlled Memory</span><h1>{zh ? "记忆中心" : "Memory Center"}</h1><p className="muted">{zh ? "你决定系统记住什么，也可以随时查看原因、修改或真正遗忘。" : "You decide what the system remembers. Inspect why, edit it, or truly forget it."}</p></div>
        <button className="btn" onClick={exportData}><Download size={16} /> {zh ? "导出" : "Export"}</button>
      </div>

      <div className="memory-metrics">
        <Metric icon={<Brain />} label={zh ? "有效记忆" : "Active memories"} value={active} />
        <Metric icon={<ShieldCheck />} label={zh ? "待你确认" : "Pending confirmation"} value={proposals.data?.proposals.length ?? 0} />
        <Metric icon={<Search />} label={zh ? "关联项目" : "Projects"} value={projects} />
      </div>

      {(proposals.data?.proposals.length ?? 0) > 0 && (
        <section className="card proposal-queue">
          <div className="section-heading"><div><span className="eyebrow">{zh ? "需要你的决定" : "Your decision required"}</span><h2>{zh ? "记忆建议" : "Memory proposals"}</h2></div><span className="connection-pill warn">{proposals.data!.proposals.length}</span></div>
          {proposals.data!.proposals.map((proposal) => <ProposalCard key={proposal.proposal_id} proposal={proposal} zh={zh} busy={action.isPending} onAction={(kind) => action.mutate({ kind, id: proposal.proposal_id })} onEdited={invalidate} />)}
        </section>
      )}

      <section className="card memory-browser">
        <div className="memory-toolbar">
          <div className="tab-list" role="tablist">
            {(["all", "project", "preferences", "episodic"] as Tab[]).map((item) => <button key={item} role="tab" aria-selected={tab === item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{tabLabel(item, zh)}</button>)}
          </div>
          <label className="memory-search"><Search size={16} /><input aria-label={zh ? "搜索记忆" : "Search memory"} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={zh ? "搜索事实、偏好或项目…" : "Search facts, preferences, or projects…"} /></label>
        </div>
        {filtered.length === 0 ? <div className="empty-state"><Brain size={34} /><h3>{zh ? "还没有匹配的记忆" : "No matching memories"}</h3><p className="muted">{zh ? "明确告诉系统一条项目事实或偏好，确认后它才会生效。" : "State a project fact or preference explicitly. It only becomes active after confirmation."}</p></div> : <div className="memory-list">{filtered.map((item) => <MemoryCard key={item.memory_id} item={item} zh={zh} onForget={() => action.mutate({ kind: "forget", id: item.memory_id })} />)}</div>}
      </section>

      {settings.data && <section className="card memory-controls"><div><h2>{zh ? "记忆控制" : "Memory controls"}</h2><p className="muted">{zh ? "关闭后不会检索或提出新记忆，已有内容保持可管理。" : "When disabled, memory is neither retrieved nor proposed; existing records remain manageable."}</p></div><label className="switch-row"><input type="checkbox" checked={settings.data.enabled} onChange={(event) => saveSettings.mutate({ ...settings.data!, enabled: event.target.checked })} /><span>{zh ? "启用受控记忆" : "Enable controlled memory"}</span></label><label className="switch-row"><input type="checkbox" checked={settings.data.automatic_low_risk} onChange={(event) => saveSettings.mutate({ ...settings.data!, automatic_low_risk: event.target.checked })} /><span>{zh ? "自动保存明确的低风险选择" : "Automatically save explicit low-risk choices"}</span></label><label className="switch-row"><input type="checkbox" checked={settings.data.preference_detection} onChange={(event) => saveSettings.mutate({ ...settings.data!, preference_detection: event.target.checked })} /><span>{zh ? "检测跨任务重复偏好（仍需确认）" : "Detect repeated cross-task preferences (confirmation still required)"}</span></label><label className="field memory-retention">{zh ? "默认保留策略" : "Default retention"}<select value={settings.data.retention} onChange={(event) => saveSettings.mutate({ ...settings.data!, retention: event.target.value })}><option value="manual">{zh ? "手动管理" : "Manual"}</option><option value="permanent">{zh ? "永久" : "Permanent"}</option><option value="project_lifetime">{zh ? "项目期间" : "Project lifetime"}</option><option value="fixed_ttl">{zh ? "固定期限" : "Fixed TTL"}</option><option value="task_only">{zh ? "仅当前任务" : "Task only"}</option></select></label></section>}
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) { return <div className="card memory-metric"><span>{icon}</span><div><strong>{value}</strong><small>{label}</small></div></div>; }

function ProposalCard({ proposal, zh, busy, onAction, onEdited }: { proposal: MemoryProposal; zh: boolean; busy: boolean; onAction: (kind: "confirm" | "reject") => void; onEdited: () => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(proposal.proposed_value);
  const edit = useMutation({ mutationFn: () => api.editConfirmMemory(proposal.proposal_id, value), onSuccess: () => { setEditing(false); onEdited(); } });
  return <article className="proposal-card"><div className="proposal-main"><div className="memory-card-head"><span className="memory-type">{proposal.memory_type}</span><span className="muted">{Math.round(proposal.confidence * 100)}%</span></div><h3>{proposal.subject} · {proposal.predicate}</h3>{editing ? <input className="proposal-edit" value={value} onChange={(event) => setValue(event.target.value)} autoFocus /> : <p>{proposal.proposed_value}</p>}<p className="why-memory"><strong>{zh ? "为什么建议：" : "Why suggested: "}</strong>{proposal.reason}</p></div><div className="proposal-actions">{editing ? <><button className="btn btn-primary" disabled={edit.isPending || !value.trim()} onClick={() => edit.mutate()}>{zh ? "保存并确认" : "Save & confirm"}</button><button className="btn" onClick={() => setEditing(false)}>{zh ? "取消" : "Cancel"}</button></> : <><button className="btn btn-primary" disabled={busy} onClick={() => onAction("confirm")}>{zh ? "确认" : "Confirm"}</button><button className="btn" onClick={() => setEditing(true)}>{zh ? "编辑" : "Edit"}</button><button className="btn btn-danger" disabled={busy} onClick={() => onAction("reject")}>{zh ? "拒绝" : "Reject"}</button></>}</div></article>;
}

function MemoryCard({ item, zh, onForget }: { item: MemoryRecord; zh: boolean; onForget: () => void }) {
  const [confirming, setConfirming] = useState(false);
  return <article className={`memory-card memory-${item.status}`}><div className="memory-card-head"><div><span className="memory-type">{item.memory_type}</span>{item.project_id && <span className="memory-scope">{item.project_id}</span>}</div><StatusBadge status={item.status} /></div><h3>{item.subject} · {item.predicate}</h3><p className="memory-value">{item.value || (zh ? "内容已擦除" : "Content erased")}</p><details><summary>{zh ? "为什么系统知道" : "Why the system knows"}</summary><dl className="detail-list"><div><dt>{zh ? "来源" : "Source"}</dt><dd>{item.source_type}</dd></div><div><dt>{zh ? "版本" : "Version"}</dt><dd>v{item.version}</dd></div><div><dt>{zh ? "隐私" : "Privacy"}</dt><dd>{item.privacy_level}</dd></div><div><dt>{zh ? "最后使用" : "Last used"}</dt><dd>{item.last_used_at ?? "—"}</dd></div></dl></details>{!['forgotten', 'expired'].includes(item.status) && (confirming ? <div className="forget-confirm" role="alert"><p>{zh ? "内容将被擦除，且不会从旧任务恢复。" : "Content will be erased and cannot return from old tasks."}</p><button className="btn btn-danger" onClick={onForget}>{zh ? "确定遗忘" : "Confirm forget"}</button><button className="btn" onClick={() => setConfirming(false)}>{zh ? "取消" : "Cancel"}</button></div> : <button className="btn memory-forget" onClick={() => setConfirming(true)}><Trash2 size={15} /> {zh ? "忘记" : "Forget"}</button>)}</article>;
}

function tabLabel(tab: Tab, zh: boolean) { const labels = zh ? { all: "全部", project: "项目", preferences: "偏好", episodic: "经历" } : { all: "All", project: "Projects", preferences: "Preferences", episodic: "Episodes" }; return labels[tab]; }
