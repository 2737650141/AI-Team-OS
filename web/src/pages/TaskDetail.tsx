// Task Detail（010 九~二十一）：Header + Timeline + Plan + Activity + Approval/Diff/Tests/Reviewer
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import { ActivityFeed } from "../components/ActivityFeed";
import { ApprovalCard } from "../components/ApprovalCard";
import { DiffViewer } from "../components/DiffViewer";
import { PlanPanel } from "../components/PlanPanel";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { useEvents } from "../hooks/useEvents";

export function TaskDetail() {
  const { runId = "" } = useParams();
  const [refresh, setRefresh] = useState(0);
  const task = useQuery({
    queryKey: ["task", runId, refresh],
    queryFn: () => api.task(runId),
    refetchInterval: 2000,
  });
  const { events, connected } = useEvents(runId);
  const evidence = useQuery({
    queryKey: ["evidence", runId],
    queryFn: () => api.evidence(runId),
  });
  const approvals = useQuery({
    queryKey: ["approvals", runId, refresh],
    queryFn: () => api.approvals(runId),
  });
  const artifacts = useQuery({
    queryKey: ["artifacts", runId],
    queryFn: () => api.artifacts(runId),
  });
  const diff = useQuery({
    queryKey: ["diff", runId, refresh],
    queryFn: () => api.diff(runId),
  });

  useEffect(() => {
    if (task.data?.current_status === "completed") {
      // 终态后停止轮询由 react-query refetchInterval 控制；此处仅刷新一次
    }
  }, [task.data?.current_status]);

  if (task.isLoading) return <div className="page">Loading task…</div>;
  if (task.isError)
    return <div className="page">Task Failed · {(task.error as Error).message}</div>;

  const t = task.data;
  if (!t) return <div className="page">Loading task…</div>;
  const testArtifact = (artifacts.data ?? []).find((a) => a.artifact_type === "test_report");

  return (
    <div className="page">
      {/* Header（010 9.1） */}
      <div className="card">
        <div className="task-header">
          <h1>{t.goal}</h1>
          <StatusBadge status={t.current_status} />
        </div>
        <div className="task-meta muted">
          Run ID: {t.run_id} · Task: {t.task_id} · Mode: {t.model_mode} · Budget:{" "}
          {t.token_budget} tok / ${t.cost_budget}
          {connected && <span className="live">● live</span>}
        </div>
      </div>

      {/* Timeline（010 十） */}
      <div className="card">
        <h2>Workflow</h2>
        <Timeline status={t.current_status} />
      </div>

      {/* Plan（010 十一） */}
      <div className="card">
        <h2>Plan</h2>
        <PlanPanel subtasks={t.subtasks ?? []} />
      </div>

      {/* Activity Feed（010 十二） */}
      <div className="card">
        <h2>Activity</h2>
        <ActivityFeed events={events} />
      </div>

      {/* Approval（010 十六/十八） */}
      {(approvals.data ?? []).length > 0 && (
        <div className="card">
          <h2>Approvals</h2>
          {(approvals.data ?? []).map((a) => (
            <ApprovalCard
              key={a.approval_id}
              approval={a}
              onDecision={() => setRefresh((x) => x + 1)}
            />
          ))}
        </div>
      )}

      {/* Diff（010 十七） */}
      {diff.data?.diff && (
        <div className="card">
          <h2>Diff</h2>
          <DiffViewer diff={diff.data.diff} files={diff.data.files} />
        </div>
      )}

      {/* Tests（010 十九） */}
      {testArtifact && (
        <div className="card">
          <h2>Tests</h2>
          <p>
            pytest · <StatusBadge status={testArtifact.artifact_type} />
            <span className="muted"> artifact {testArtifact.artifact_id}</span>
          </p>
        </div>
      )}

      {/* Reviewer（010 二十） */}
      <div className="card">
        <h2>Reviewer</h2>
        {t.rework_count > 0 && <p>Rework #{t.rework_count}</p>}
        {t.current_status === "completed" && <p className="green">Review passed — task completed.</p>}
      </div>

      {/* Evidence（010 二十一） */}
      <div className="card">
        <h2>Evidence</h2>
        {(evidence.data ?? []).length === 0 && <p className="muted">No evidence.</p>}
        {(evidence.data ?? []).map((e) => (
          <div key={e.evidence_id} className="evidence-row">
            <code>{e.evidence_id}</code> <span>{e.title}</span>{" "}
            <span className="muted">
              {e.source_type} · {e.reliability}
            </span>
          </div>
        ))}
      </div>

    </div>
  );
}
