import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import type { PersonalizationItem } from "../api/types";
import { useI18n } from "../i18n";

export function Personalization() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const [project, setProject] = useState("");
  const data = useQuery({ queryKey: ["personalization", project], queryFn: () => api.personalization(project || undefined, "code") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["personalization"] });
  const reset = useMutation({ mutationFn: (payload: { field?: string; project?: string }) => api.resetPersonalization(payload.project || undefined, payload.field), onSuccess: refresh });
  const decide = useMutation({ mutationFn: (payload: { id: string; decision: string }) => api.decidePersonalization(payload.id, payload.decision, project || undefined), onSuccess: refresh });
  return <div className="page personalization-page">
    <div className="page-heading"><div><span className="eyebrow">M4-B · Adaptive Personalization</span><h1>{zh ? "AI Team OS 如何适应你" : "How AI Team OS works with you"}</h1><p className="muted">{zh ? "所有适配都来自已确认记忆或低风险行为，并且永远不能降低审批、安全、工具和预算限制。" : "Adaptation comes from confirmed memory or low-risk behavior and can never weaken approval, security, tool, or budget limits."}</p></div><button className="btn" onClick={() => reset.mutate({})}><RotateCcw size={15} />{zh ? "重置全部" : "Reset all"}</button></div>
    <section className="card personalization-scope"><label className="field">{zh ? "项目范围（可选）" : "Project scope (optional)"}<input value={project} onChange={(event) => setProject(event.target.value)} placeholder={zh ? "例如：demo" : "e.g. demo"} /></label>{project && <button className="btn" onClick={() => reset.mutate({ project })}>{zh ? "重置此项目" : "Reset project"}</button>}</section>
    {(data.data?.proposals.length ?? 0) > 0 && <section className="card proposal-queue"><div className="section-heading"><div><span className="eyebrow">{zh ? "需要你的决定" : "Your choice"}</span><h2>{zh ? "个性化建议" : "Personalization proposals"}</h2></div></div>{data.data!.proposals.map((proposal) => <article className="proposal-card" key={proposal.proposal_id}><div><h3>{proposal.subject}</h3><p>{zh ? `看起来你通常喜欢：${proposal.proposed_value}` : `It looks like you usually prefer: ${proposal.proposed_value}`}</p><small className="muted">{proposal.reason}</small></div><div className="proposal-actions"><button className="btn btn-primary" onClick={() => decide.mutate({ id: proposal.proposal_id, decision: "yes" })}>{zh ? "是" : "Yes"}</button><button className="btn" onClick={() => decide.mutate({ id: proposal.proposal_id, decision: "project" })}>{zh ? "只在这个项目" : "Only this project"}</button><button className="btn" onClick={() => decide.mutate({ id: proposal.proposal_id, decision: "no" })}>{zh ? "不用" : "No"}</button><button className="btn btn-danger" onClick={() => decide.mutate({ id: proposal.proposal_id, decision: "suppress" })}>{zh ? "不要再问" : "Don't ask again"}</button></div></article>)}</section>}
    <div className="personalization-grid">{(data.data?.profile.items ?? []).map((item) => <PreferenceCard key={item.field} item={item} project={project} zh={zh} onChanged={refresh} onReset={() => reset.mutate({ field: item.field, project })} />)}</div>
    <section className="card personalization-security"><SlidersHorizontal /><div><h2>{zh ? "不可适配的安全边界" : "Security never adapts"}</h2><p className="muted">{zh ? "人工审批、工具权限、预算、工作区、Secret 与 SSRF 策略始终由确定性安全层控制。" : "Human approval, tool permissions, budgets, workspace, secrets, and SSRF remain controlled by deterministic policy."}</p></div></section>
  </div>;
}

function PreferenceCard({ item, project, zh, onChanged, onReset }: { item: PersonalizationItem; project: string; zh: boolean; onChanged: () => void; onReset: () => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(item.value);
  const save = useMutation({ mutationFn: (enabled: boolean) => api.savePersonalizationControl({ field: item.field, value, enabled, project_id: project || null, task_type: "code" }), onSuccess: () => { setEditing(false); onChanged(); } });
  return <article className={`card personalization-card ${item.enabled ? "" : "disabled"}`}><div className="memory-card-head"><span className="memory-type">{item.field}</span><span className="memory-scope">{item.scope}</span></div><h2>{label(item.field, zh)}</h2>{editing ? <input value={value} onChange={(event) => setValue(event.target.value)} /> : <p className="personalization-value">{item.enabled ? item.value : (zh ? "已禁用" : "Disabled")}</p>}<p className="muted">{Math.round(item.confidence * 100)}% · {zh ? "来源" : "Source"}: {item.source_refs.length ? `${item.source_refs.length} ${zh ? "条已确认偏好" : "confirmed preferences"}` : item.source}</p><details><summary>{zh ? "为什么？" : "Why?"}</summary><p>{item.reason}</p>{item.current_task_override && <p className="signal-warning">{zh ? "当前任务覆盖长期偏好" : "Current task overrides the long-term preference"}</p>}</details><div className="provider-actions">{editing ? <><button className="btn btn-primary" onClick={() => save.mutate(true)}>{zh ? "保存" : "Save"}</button><button className="btn" onClick={() => setEditing(false)}>{zh ? "取消" : "Cancel"}</button></> : <><button className="btn" onClick={() => setEditing(true)}>{zh ? "编辑" : "Edit"}</button><button className="btn" onClick={() => save.mutate(!item.enabled)}>{item.enabled ? (zh ? "禁用" : "Disable") : (zh ? "启用" : "Enable")}</button><button className="btn" onClick={onReset}>{zh ? "恢复默认" : "Reset"}</button></>}</div></article>;
}

function label(field: string, zh: boolean) {
  const labels: Record<string, [string, string]> = { language: ["语言", "Language"], response_detail: ["回答详细度", "Response detail"], planning_style: ["规划方式", "Planning style"], execution_style: ["执行方式", "Execution style"], approval_preference: ["审批偏好", "Approval preference"], research_depth: ["研究深度", "Research depth"], tool_preference: ["工具偏好", "Tool preference"], report_style: ["报告风格", "Report style"], risk_tolerance_for_suggestions: ["建议风险风格", "Suggestion risk style"] };
  return labels[field]?.[zh ? 0 : 1] ?? field;
}
