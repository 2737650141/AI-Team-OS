import { useQuery } from "@tanstack/react-query";
import { FileDiff, Files, GitCompare, ListVideo } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import type { RuntimeEvent, TaskDetail, UsageSummary } from "../api/types";
import { useI18n } from "../i18n";
import { ActivityFeed } from "./ActivityFeed";

type Tab = "overview" | "files" | "changes" | "activity";

export function RightInspector({ runId, task, usage, events, connected }: {
  runId: string | undefined;
  task: TaskDetail | undefined;
  usage: UsageSummary | undefined;
  events: RuntimeEvent[];
  connected: boolean;
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
      <div className="inspector-tabs" role="tablist">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "on" : ""} onClick={() => setTab(key)}><Icon size={13} />{label}</button>
        ))}
      </div>
      <div className="inspector-body">
        {tab === "overview" && <OverviewTab task={task} usage={usage} zh={zh} />}
        {tab === "files" && <FilesTab diff={diff.data} zh={zh} />}
        {tab === "changes" && <ChangesTab diff={diff.data} zh={zh} />}
        {tab === "activity" && <ActivityTab events={events} connected={connected} zh={zh} />}
      </div>
    </aside>
  );
}

function OverviewTab({ task, usage, zh }: { task?: TaskDetail; usage?: UsageSummary; zh: boolean }) {
  if (!task) return <Empty label={zh ? "运行任务后这里会显示概览。" : "Run a task to see its overview here."} />;
  return <dl className="inspector-overview">
    <div><dt>{zh ? "状态" : "Status"}</dt><dd>{task.current_status}</dd></div>
    <div><dt>{zh ? "目标" : "Goal"}</dt><dd className="wrap">{task.goal}</dd></div>
    <div><dt>Model</dt><dd>{task.model_identity?.badge ?? task.model_mode} · {task.model_identity?.provider ?? "—"}</dd></div>
    <div><dt>{zh ? "Token 预算" : "Token budget"}</dt><dd>{formatTokens(task.token_budget)}</dd></div>
    <div><dt>{zh ? "已用 Token" : "Tokens used"}</dt><dd>{formatTokens(usage?.total_tokens)}</dd></div>
    <div><dt>{zh ? "子任务" : "Subtasks"}</dt><dd>{task.subtasks.length}</dd></div>
    <div><dt>{zh ? "返工" : "Rework"}</dt><dd>{task.rework_count}</dd></div>
  </dl>;
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

function formatTokens(value?: number | null) {
  if (value == null) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}K` : String(value);
}
