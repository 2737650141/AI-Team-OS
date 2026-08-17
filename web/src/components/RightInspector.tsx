import { useQuery } from "@tanstack/react-query";
import { FileDiff, Files, GitCompare, ListVideo, X } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import type { RuntimeEvent, TaskDetail, UsageSummary } from "../api/types";
import { useI18n } from "../i18n";
import { ActivityFeed } from "./ActivityFeed";

type Tab = "overview" | "files" | "changes" | "activity";

export function RightInspector({ runId, task, usage, events, connected, onClose }: {
  runId: string | undefined;
  task: TaskDetail | undefined;
  usage: UsageSummary | undefined;
  events: RuntimeEvent[];
  connected: boolean;
  onClose?: () => void;
}) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [tab, setTab] = useState<Tab>("overview");
  const diff = useQuery({
    queryKey: ["inspector-diff", runId],
    queryFn: () => api.diff(runId!),
    enabled: !!runId && tab === "changes",
  });
  const tabs: Array<{ key: Tab; label: string; icon: typeof Files }> = [
    { key: "overview", label: zh ? "概览" : "Overview", icon: GitCompare },
    { key: "files", label: zh ? "文件" : "Files", icon: Files },
    { key: "changes", label: zh ? "变更" : "Changes", icon: FileDiff },
    { key: "activity", label: zh ? "动态" : "Activity", icon: ListVideo },
  ];
  return (
    <aside className="right-inspector" aria-label={zh ? "检查器" : "Inspector"}>
      {onClose && <button className="inspector-close" onClick={onClose} aria-label={zh ? "关闭检查器" : "Close Inspector"}><X size={13} /></button>}
      <div className="inspector-tabs" role="tablist">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "on" : ""} onClick={() => setTab(key)}><Icon size={13} />{label}</button>
        ))}
      </div>
      <div className="inspector-body">
        {tab === "overview" && <OverviewTab task={task} usage={usage} events={events} zh={zh} />}
        {tab === "files" && <FilesTab diff={diff.data} zh={zh} />}
        {tab === "changes" && <ChangesTab diff={diff.data} zh={zh} />}
        {tab === "activity" && <ActivityTab events={events} connected={connected} zh={zh} />}
      </div>
    </aside>
  );
}

function OverviewTab({ task, usage, events, zh }: { task?: TaskDetail; usage?: UsageSummary; events: RuntimeEvent[]; zh: boolean }) {
  const [goalExpanded, setGoalExpanded] = useState(false);
  if (!task) return <Empty label={zh ? "运行任务后这里会显示概览。" : "Run a task to see its overview here."} />;
  const currentAgent = task.subtasks.find((item) => ["running", "working", "in_progress"].includes(item.status))?.role
    ?? [...events].reverse().find((event) => event.actor_type === "agent")?.actor_id
    ?? usage?.by_agent?.[0]?.name
    ?? (zh ? "无" : "None");
  const goalNeedsToggle = task.goal.length > 120;
  return <div className="inspector-overview">
    <dl className="inspector-primary">
      <div><dt>{zh ? "状态" : "Status"}</dt><dd>{task.current_status}</dd></div>
      <div><dt>{zh ? "当前 Agent" : "Current agent"}</dt><dd>{currentAgent}</dd></div>
      <div><dt>Model</dt><dd>{task.model_identity?.badge ?? task.model_mode} · {task.model_identity?.provider ?? "—"}</dd></div>
      <div><dt>Context</dt><dd>{formatContextPercent(usage?.context?.percentage, zh)}</dd></div>
      <div><dt>Tokens</dt><dd>{formatTokens(usage?.total_tokens)}{task.token_budget != null ? ` / ${formatTokens(task.token_budget)}` : ""}</dd></div>
      <div><dt>{zh ? "运行时间" : "Runtime"}</dt><dd>{formatRuntime(usage?.runtime_ms)}</dd></div>
    </dl>
    <details className="inspector-more">
      <summary>{zh ? "更多详情" : "More details"}</summary>
      <dl>
        <div className="inspector-goal-row"><dt>{zh ? "目标" : "Goal"}</dt><dd className="wrap"><div className={`inspector-goal ${goalExpanded ? "expanded" : ""}`}>{task.goal}</div>{goalNeedsToggle && <button className="inspector-goal-toggle" type="button" aria-expanded={goalExpanded} onClick={() => setGoalExpanded((expanded) => !expanded)}>{goalExpanded ? (zh ? "收起目标" : "Show less") : (zh ? "查看完整目标" : "View full goal")}</button>}</dd></div>
        <div><dt>{zh ? "费用" : "Cost"}</dt><dd>{usage?.cost_total == null ? "Unavailable" : `$${usage.cost_total.toFixed(4)}`}</dd></div>
        <div><dt>{zh ? "子任务" : "Subtasks"}</dt><dd>{task.subtasks.length}</dd></div>
        <div><dt>{zh ? "返工" : "Rework"}</dt><dd>{task.rework_count}</dd></div>
      </dl>
    </details>
  </div>;
}

function FilesTab({ diff, zh }: { diff?: { diff: string; files?: Array<{ path: string; status: string }> }; zh: boolean }) {
  const files = diff?.files?.length ? diff.files : diff?.diff ? [{ path: zh ? "diff（未解析文件列表）" : "diff (files not parsed)", status: "M" }] : [];
  if (files.length === 0) return <Empty label={zh ? "暂无文件变更。" : "No file changes yet."} />;
  return <ul className="inspector-files">{files.map((file, index) => <li key={`${file.path}-${index}`}><span className={`file-status ${file.status.toLowerCase()}`}>{file.status}</span><code>{file.path}</code></li>)}</ul>;
}

function ChangesTab({ diff, zh }: { diff?: { diff: string; files?: Array<{ path: string; status: string }> }; zh: boolean }) {
  if (!diff?.diff) return <Empty label={zh ? "暂无变更内容。" : "No changes yet."} />;
  return <pre className="inspector-diff">{diff.diff.slice(0, 6000)}</pre>;
}

function ActivityTab({ events, connected, zh }: { events: RuntimeEvent[]; connected: boolean; zh: boolean }) {
  if (events.length === 0) return <Empty label={zh ? "暂无活动。" : "No activity yet."} />;
  return <div className="inspector-activity"><span className={`inspector-live ${connected ? "on" : ""}`}>{connected ? (zh ? "实时" : "Live") : (zh ? "同步中" : "Syncing")}</span><ActivityFeed events={events} /></div>;
}

function Empty({ label }: { label: string }) {
  return <p className="inspector-empty">{label}</p>;
}

function formatContextPercent(value: number | null | undefined, _zh: boolean) {
  if (value == null) return "Unavailable";
  if (value > 0 && value < 0.01) return "<1%";
  return `${Math.round(value * 100)}%`;
}

function formatTokens(value?: number | null) {
  if (value == null) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}K` : String(value);
}

function formatRuntime(value?: number | null) {
  if (value == null) return "Unavailable";
  return value >= 60_000 ? `${Math.floor(value / 60_000)}m ${Math.round((value % 60_000) / 1000)}s` : `${Math.round(value / 1000)}s`;
}
