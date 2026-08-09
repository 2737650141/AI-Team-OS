// Dashboard（010 七/八）：System Health + Metrics + New Task + Recent Tasks + Agent Team
// 010-B 五：提供明显 Demo 入口（Try Demo Mode）；010-B 九：i18n
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";

export function Dashboard() {
  const { lang, t } = useI18n();
  const qc = useQueryClient();
  const nav = useNavigate();
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 3000 });
  const [goal, setGoal] = useState("");
  const [mode, setMode] = useState("fake");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [project, setProject] = useState("");
  const [memoryProject, setMemoryProject] = useState("default");
  const activeSummary = dash.data?.recent_tasks.find((task) => ["running", "paused"].includes(task.status));
  const activeDetail = useQuery({
    queryKey: ["dashboard-active-task", activeSummary?.run_id],
    queryFn: () => api.task(activeSummary!.run_id),
    enabled: !!activeSummary,
    refetchInterval: 3000,
  });

  const create = useMutation({
    mutationFn: (body: { goal: string; model_mode: string; project_alias?: string; project_id?: string }) =>
      api.createTask(body),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      nav(`/tasks/${res.run_id}`);
    },
  });

  const data = dash.data;

  return (
    <div className="page">
      <h1>{t("dash.title")}</h1>
      <section className={`card command-overview ${activeSummary ? "team-working" : ""}`}>
        <div className="command-title">
          <div>
            <span className="eyebrow">JARVIS Control Surface</span>
            <h2>{activeSummary ? t("dash.teamWorking") : t("dash.teamReady")}</h2>
          </div>
          <StatusBadge status={activeSummary?.status ?? "online"} />
        </div>
        <div className="overview-grid">
          <Overview label={t("dash.systemStatus")} value={data?.system.backend ? displayLabel(data.system.backend.toLowerCase(), lang) : t("dash.loading")} />
          <Overview label={t("dash.activeAiTeam")} value={activeSummary ? t("st.active") : t("st.idle")} />
          <Overview label={t("dash.pendingApproval")} value={String(data?.metrics.pending_approvals ?? 0)} />
          <Overview label={t("dash.currentTask")} value={activeSummary ? displayLabel(activeSummary.goal, lang) : t("dash.none")} />
        </div>
        {activeSummary && (
          <div className="working-context">
            <span><small>{t("dash.currentPhase")}</small><strong>{displayLabel(activeSummary.status, lang)}</strong></span>
            <span><small>{t("dash.currentAgent")}</small><strong>{displayLabel(activeDetail.data?.subtasks.find((subtask) => ["running", "executed", "rejected"].includes(subtask.status))?.role ?? (activeSummary.status === "paused" ? "executor" : "supervisor"), lang)}</strong></span>
            <span><small>{t("dash.currentSubtask")}</small><strong>{activeDetail.data?.subtasks.find((subtask) => ["running", "executed", "rejected"].includes(subtask.status))?.title ?? t("dash.coordinating")}</strong></span>
          </div>
        )}
      </section>
      {/* New Task（010 八/二十三） */}
      <div className="card new-task">
        <input
          className="goal-input"
          placeholder={t("dash.placeholder")}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && goal.trim()) {
              create.mutate({ goal, model_mode: mode, project_alias: project || undefined, project_id: memoryProject || "default" });
            }
          }}
        />
        <div className="new-task-row">
          <label className="seg">
            <button className={mode === "fake" ? "on" : ""} onClick={() => setMode("fake")}>
              {t("dash.demo")}
            </button>
            <button className={mode === "real" ? "on" : ""} onClick={() => setMode("real")}>
              {t("dash.real")}
            </button>
          </label>
          <button
            className="btn btn-primary"
            disabled={!goal.trim() || create.isPending}
            onClick={() =>
              create.mutate({ goal, model_mode: mode, project_alias: project || undefined, project_id: memoryProject || "default" })
            }
          >
            {t("dash.startTask")}
          </button>
        </div>
        {/* 010-B 五：明显 Demo 入口 */}
        <div className="demo-entry">
          <button
            className="btn btn-demo"
            disabled={create.isPending}
            onClick={() =>
              create.mutate({
                goal: "sandbox_code_fix",
                model_mode: "fake",
                project_alias: project || "sample-python",
                project_id: memoryProject || "default",
              })
            }
          >
            🚀 Try Demo Mode
          </button>
          <span className="muted">{t("dash.demoHint")}</span>
        </div>
        <details open={showAdvanced} onToggle={(e) => setShowAdvanced(e.currentTarget.open)}>
          <summary>{t("dash.advanced")}</summary>
          <label className="field">
            {t("dash.project")}
            <input value={project} onChange={(e) => setProject(e.target.value)} placeholder="sample-python" />
          </label>
          <label className="field">
            {lang === "zh" ? "记忆项目" : "Memory project"}
            <input value={memoryProject} onChange={(e) => setMemoryProject(e.target.value)} placeholder="default" />
          </label>
        </details>
        {create.isError && <p className="error">{(create.error as Error).message}</p>}
      </div>

      {/* System Health（010 八） */}
      <div className="card">
        <h2>{t("dash.systemHealth")}</h2>
        <div className="health-grid">
          {dash.isError ? (
            <div className="error">
              {t("dash.backendOffline")} {" "}
              <button className="btn" onClick={() => dash.refetch()}>{t("common.retry")}</button>
            </div>
          ) : data
            ? Object.entries(data.system).map(([k, v]) => (
                <div key={k} className="health-item">
                  <span>{displayLabel(k, lang)}</span>
                  <StatusBadge status={v.toLowerCase()} />
                </div>
              ))
            : t("dash.loading")}
        </div>
      </div>

      {/* Metrics（010 八） */}
      <div className="card">
        <h2>{t("dash.metrics")}</h2>
        {data && (
          <div className="metrics-grid">
            <Metric label={t("dash.active")} value={data.metrics.active_tasks} />
            <Metric label={t("dash.completed")} value={data.metrics.completed_tasks} />
            <Metric label={t("dash.failed")} value={data.metrics.failed_tasks} />
            <Metric label={t("dash.pendingApprovals")} value={data.metrics.pending_approvals} />
            <Metric label={t("dash.evidence")} value={data.metrics.evidence_count} />
            <Metric label={t("dash.toolCalls")} value={data.metrics.tool_calls} />
            <Metric label={t("dash.tokens")} value={data.metrics.tokens} />
            <Metric label={t("dash.cost")} value={`$${data.metrics.cost.toFixed(4)}`} />
          </div>
        )}
      </div>

      {/* Recent Tasks（010 八） */}
      <div className="card">
        <h2>{t("dash.recentTasks")}</h2>
        <table className="table">
          <thead>
            <tr>
              <th>{t("dash.goal")}</th>
              <th>{t("dash.status")}</th>
              <th>{t("dash.model")}</th>
              <th>{t("dash.tokens")}</th>
              <th>{t("dash.cost")}</th>
            </tr>
          </thead>
          <tbody>
            {(data?.recent_tasks ?? []).map((tr) => (
              <tr key={tr.run_id} onClick={() => nav(`/tasks/${tr.run_id}`)} className="clickable">
                <td>{displayLabel(tr.goal, lang)}</td>
                <td>
                  <StatusBadge status={tr.status} />
                </td>
                <td>{tr.model_mode === "fake" ? t("dash.demo") : t("dash.real")}</td>
                <td>{tr.tokens}</td>
                <td>${tr.cost.toFixed(4)}</td>
              </tr>
            ))}
            {(data?.recent_tasks ?? []).length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  {t("dash.noTasks")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Agent Team（010 八） */}
      <div className="card">
        <h2>{t("dash.agentTeam")}</h2>
        <div className="agent-grid">
          {(data?.agent_team ?? []).map((a) => (
            <div key={a.role} className="agent-card">
              <strong>{displayLabel(a.role, lang)}</strong>
              <StatusBadge status={a.status} />
              <span className="muted">{a.model}</span>
              <span className="muted">
                {a.tokens} {t("dash.tokenUnit")}
              </span>
              {a.current_task && <span className="muted">{t("dash.currentTask")}: {displayLabel(a.current_task, lang)}</span>}
              {a.last_action && <span className="muted">{t("agents.lastAction")}: {displayLabel(a.last_action, lang)}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  );
}

function Overview({ label, value }: { label: string; value: string }) {
  return <div className="overview-item"><span>{label}</span><strong>{value}</strong></div>;
}
