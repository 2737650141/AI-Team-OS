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
import { useI18n } from "../i18n";

export function TaskDetail() {
  const { t } = useI18n();
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

  if (task.isLoading) return <div className="page">{t("task.loading")}</div>;
  if (task.isError)
    return (
      <div className="page">
        {t("task.taskFailed")} · {(task.error as Error).message}
      </div>
    );

  const taskData = task.data;
  if (!taskData) return <div className="page">{t("task.loading")}</div>;
  const testArtifact = (artifacts.data ?? []).find((a) => a.artifact_type === "test_report");

  return (
    <div className="page">
      {/* Header（010 9.1） */}
      <div className="card">
        <div className="task-header">
          <h1>{taskData.goal}</h1>
          <StatusBadge status={taskData.current_status} />
        </div>
        <div className="task-meta muted">
          {t("task.runId")}: {taskData.run_id} · {t("task.task")}: {taskData.task_id} ·{" "}
          {t("task.mode")}: {taskData.model_mode} · {t("task.budget")}: {taskData.token_budget}{" "}
          tok / ${taskData.cost_budget}
          {connected && <span className="live">● {t("task.live")}</span>}
        </div>
      </div>

      {/* Timeline（010 十） */}
      <div className="card">
        <h2>{t("task.workflow")}</h2>
        <Timeline status={taskData.current_status} />
      </div>

      {/* Plan（010 十一） */}
      <div className="card">
        <h2>{t("task.plan")}</h2>
        <PlanPanel subtasks={taskData.subtasks ?? []} />
      </div>

      {/* Activity Feed（010 十二） */}
      <div className="card">
        <h2>{t("task.activity")}</h2>
        <ActivityFeed events={events} />
      </div>

      {/* Approval（010 十六/十八） */}
      {(approvals.data ?? []).length > 0 && (
        <div className="card">
          <h2>{t("task.approvals")}</h2>
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
          <h2>{t("task.diff")}</h2>
          <DiffViewer diff={diff.data.diff} files={diff.data.files} />
        </div>
      )}

      {/* Tests（010 十九） */}
      {testArtifact && (
        <div className="card">
          <h2>{t("task.tests")}</h2>
          <p>
            pytest · <StatusBadge status={testArtifact.artifact_type} />
            <span className="muted">
              {" "}
              {t("task.artifact")} {testArtifact.artifact_id}
            </span>
          </p>
        </div>
      )}

      {/* Reviewer（010 二十） */}
      <div className="card">
        <h2>{t("task.reviewer")}</h2>
        {taskData.rework_count > 0 && (
          <p>
            {t("task.rework")} {taskData.rework_count}
          </p>
        )}
        {taskData.current_status === "completed" && <p className="green">{t("task.reviewPassed")}</p>}
      </div>

      {/* Evidence（010 二十一） */}
      <div className="card">
        <h2>{t("task.evidence")}</h2>
        {(evidence.data ?? []).length === 0 && <p className="muted">{t("task.noEvidence")}</p>}
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

