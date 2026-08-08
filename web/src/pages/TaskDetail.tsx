import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { RuntimeEvent } from "../api/types";
import { ActivityFeed } from "../components/ActivityFeed";
import { ApprovalCard } from "../components/ApprovalCard";
import { DiffViewer } from "../components/DiffViewer";
import { EvidenceCard } from "../components/EvidenceCard";
import { PlanPanel } from "../components/PlanPanel";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { useEvents } from "../hooks/useEvents";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";

export function TaskDetail() {
  const { lang, t } = useI18n();
  const { runId = "" } = useParams();
  const [refresh, setRefresh] = useState(0);
  const task = useQuery({
    queryKey: ["task", runId, refresh],
    queryFn: () => api.task(runId),
    refetchInterval: 2000,
  });
  const { events, connected } = useEvents(runId);
  const presentedEvents = usePresentedEvents(events, task.data?.model_mode !== "real", runId);
  const evidence = useQuery({ queryKey: ["evidence", runId], queryFn: () => api.evidence(runId) });
  const approvals = useQuery({ queryKey: ["approvals", runId, refresh], queryFn: () => api.approvals(runId) });
  const artifacts = useQuery({ queryKey: ["artifacts", runId, refresh], queryFn: () => api.artifacts(runId) });
  const testArtifact = (artifacts.data ?? []).find((artifact) => artifact.artifact_type === "test_report");
  const testReport = useQuery({
    queryKey: ["artifact", testArtifact?.artifact_id],
    queryFn: () => api.artifact(testArtifact!.artifact_id),
    enabled: !!testArtifact,
  });
  const diff = useQuery({ queryKey: ["diff", runId, refresh], queryFn: () => api.diff(runId) });

  if (task.isLoading) return <div className="page">{t("task.loading")}</div>;
  if (task.isError) return <div className="page"><div className="card"><p className="error">{t("task.taskFailed")} · {(task.error as Error).message}</p><Link to="/tasks">{t("task.backToTasks")}</Link></div></div>;
  const taskData = task.data;
  if (!taskData) return <div className="page">{t("task.loading")}</div>;

  const presenting = taskData.model_mode === "fake" && presentedEvents.length < events.length;
  const lastEvent = presentedEvents.at(-1);
  const latestCompleted = [...presentedEvents].reverse().find((event) => ["subtask_completed", "tool_completed", "test_completed", "review_passed", "patch_applied", "task_completed"].includes(event.event_type));
  const currentSubtaskId = String(lastEvent?.payload_safe.subtask_id ?? "");
  const currentSubtask = taskData.subtasks.find((subtask) => subtask.subtask_id === currentSubtaskId)
    ?? taskData.subtasks.find((subtask) => ["running", "executed", "rejected"].includes(subtask.status));
  const parsedTest = parseTestReport(testReport.data?.content);
  const changedFiles = diff.data?.files?.map((file) => file.path) ?? Array.from(new Set((approvals.data ?? []).filter((approval) => approval.status === "approved").flatMap((approval) => approval.target_paths)));
  const finalReport = parseFinalResult(taskData.final_result);
  const duration = eventDuration(events);
  const supervisorStatus = taskData.current_status === "paused" ? "waiting_approval" : taskData.current_status;

  return (
    <div className="page task-detail-page">
      <div className="card task-hero">
        <div className="task-header"><div><span className="eyebrow">{t("task.task")}</span><h1>{displayLabel(taskData.goal, lang)}</h1></div><StatusBadge status={taskData.current_status} /></div>
        <div className="task-meta muted">
          {t("task.runId")}: {taskData.run_id} · {t("task.mode")}: {taskData.model_mode === "fake" ? "Demo" : t("dash.real")} · {t("task.budget")}: {taskData.token_budget} Token / ${taskData.cost_budget}
          {connected && <span className="live">● {t("task.live")}</span>}
        </div>
      </div>

      <section className="card supervisor-presence">
        <div className="presence-head"><div><span className="eyebrow">{t("task.supervisor")}</span><h2>{t("task.supervisorPresence")}</h2></div><StatusBadge status={supervisorStatus} /></div>
        <p className="presence-summary">{supervisorMessage(taskData.current_status, lastEvent, lang)}</p>
        <div className="presence-grid">
          <Presence label={t("task.currentAction")} value={lastEvent ? displayLabel(lastEvent.event_type, lang) : t("task.preparing")} />
          <Presence label={t("task.currentSubtask")} value={currentSubtask?.title ?? "—"} />
          <Presence label={t("task.activeAgent")} value={displayLabel(lastEvent?.actor_type ?? currentSubtask?.role ?? "supervisor", lang)} />
          <Presence label={t("task.latestCompleted")} value={latestCompleted ? displayLabel(latestCompleted.event_type, lang) : "—"} />
        </div>
      </section>

      <div className="card"><h2>{t("task.workflow")}</h2><Timeline status={taskData.current_status} /></div>
      <div className="card"><h2>{t("task.plan")}</h2><PlanPanel subtasks={taskData.subtasks ?? []} /></div>
      <div className="card"><div className="section-heading"><h2>{t("task.activity")}</h2>{presenting && <span className="demo-pacing">{t("task.demoPacing")}</span>}</div><ActivityFeed events={presentedEvents} presenting={presenting} /></div>

      {(approvals.data ?? []).length > 0 && <div className="card approval-section"><h2>{t("task.approvals")}</h2>{(approvals.data ?? []).map((approval) => <ApprovalCard key={approval.approval_id} approval={approval} onDecision={() => setRefresh((value) => value + 1)} />)}</div>}

      {diff.data?.diff && <div className="card diff-section"><h2>{t("task.diff")}</h2><DiffViewer diff={diff.data.diff} files={diff.data.files} /></div>}

      <div className="task-two-column">
        <div className={`card ${parsedTest && parsedTest.return_code !== 0 ? "signal-danger" : ""}`}>
          <h2>{t("task.tests")}</h2>
          {testArtifact ? <><p>pytest · <StatusBadge status={parsedTest?.return_code === 0 ? "passed" : "failed"} /></p>{parsedTest && <><p className="muted">{t("task.exitCode")}: {parsedTest.return_code} · {t("task.duration")}: {parsedTest.duration_ms} ms</p><details><summary>{t("task.testOutput")}</summary><pre className="json">stdout: {parsedTest.stdout || "—"}{"\n"}stderr: {parsedTest.stderr || "—"}</pre></details></>}</> : <p className="muted">{t("task.testsPending")}</p>}
        </div>
        <div className="card">
          <h2>{t("task.reviewer")}</h2>
          {taskData.rework_count > 0 && <p className="signal-warning">{t("task.rework")} {taskData.rework_count}</p>}
          {taskData.current_status === "completed" ? <p className="green">{t("task.reviewPassed")}</p> : <p className="muted">{t("task.reviewerMonitoring")}</p>}
        </div>
      </div>

      <div className="card"><h2>{t("task.evidence")}</h2>{(evidence.data ?? []).length === 0 && <p className="muted">{t("task.noEvidence")}</p>}{(evidence.data ?? []).map((item) => <EvidenceCard key={item.evidence_id} evidence={item} />)}</div>

      {taskData.current_status === "completed" && (
        <section className="card completion-summary">
          <div className="completion-title"><div><span className="eyebrow">{t("task.completedSummary")}</span><h2>{t("task.whatHappened")}</h2></div><StatusBadge status="completed" /></div>
          <p className="completion-result">{productText(finalReport.summary ?? taskData.final_result, lang) ?? t("task.reviewPassed")}</p>
          <div className="summary-grid">
            <Summary label={t("task.changedFiles")} value={changedFiles.length ? changedFiles.join(", ") : "—"} />
            <Summary label={t("task.tests")} value={parsedTest ? (parsedTest.return_code === 0 ? t("st.passed") : t("st.failed")) : t("task.notRecorded")} />
            <Summary label={t("task.reviewer")} value={t("st.passed")} />
            <Summary label={t("task.evidenceCount")} value={String(evidence.data?.length ?? 0)} />
          </div>
          <div className="completion-metrics">
            <span>Token <strong>{taskData.budget_usage.tokens ?? 0}</strong></span>
            <span>{t("dash.cost")} <strong>${Number(taskData.budget_usage.cost ?? 0).toFixed(4)}</strong></span>
            <span>{t("task.duration")} <strong>{duration}</strong></span>
          </div>
        </section>
      )}
    </div>
  );
}

function productText(value: string | null | undefined, lang: "zh" | "en") {
  if (!value) return null;
  return value.replaceAll("sandbox_code_fix", displayLabel("sandbox_code_fix", lang));
}

function usePresentedEvents(events: RuntimeEvent[], paced: boolean, runId: string) {
  const [presented, setPresented] = useState<RuntimeEvent[]>([]);
  useEffect(() => setPresented([]), [runId]);
  useEffect(() => {
    if (!paced) {
      setPresented(events);
      return;
    }
    if (presented.length >= events.length) return;
    const timer = window.setTimeout(() => setPresented(events.slice(0, presented.length + 1)), 420);
    return () => window.clearTimeout(timer);
  }, [events, paced, presented.length]);
  return presented;
}

function Presence({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function Summary({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

function supervisorMessage(status: string, event: RuntimeEvent | undefined, lang: "zh" | "en") {
  if (status === "completed") return lang === "zh" ? "主管已确认执行、测试与审查结果，任务可以交付。" : "The supervisor confirmed execution, tests, and review; the task is ready.";
  if (status === "paused") return lang === "zh" ? "主管已暂停执行，正在等待你的审批决定。" : "The supervisor paused execution and is waiting for your approval.";
  if (status === "failed") return lang === "zh" ? "主管已停止流程并保留失败上下文供检查。" : "The supervisor stopped the workflow and preserved the failure context.";
  return event ? (lang === "zh" ? "主管正在协调当前阶段并监控交付条件。" : "The supervisor is coordinating the current stage and monitoring delivery conditions.") : (lang === "zh" ? "主管正在准备任务上下文。" : "The supervisor is preparing task context.");
}

function parseFinalResult(content: string | null): { summary?: string } {
  if (!content) return {};
  try { return JSON.parse(content) as { summary?: string }; } catch { return { summary: content }; }
}

function eventDuration(events: RuntimeEvent[]) {
  if (events.length < 2) return "<1s";
  const start = Date.parse(events[0].timestamp);
  const end = Date.parse(events.at(-1)!.timestamp);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function parseTestReport(content?: string): { return_code: number; stdout: string; stderr: string; duration_ms: number } | null {
  if (!content) return null;
  try {
    const parsed = JSON.parse(content) as Record<string, unknown>;
    return { return_code: Number(parsed.return_code ?? -1), stdout: String(parsed.stdout ?? ""), stderr: String(parsed.stderr ?? ""), duration_ms: Number(parsed.duration_ms ?? 0) };
  } catch { return null; }
}
