// Dashboard（010 七/八）：System Health + Metrics + New Task + Recent Tasks + Agent Team
// 010-B 五：提供明显 Demo 入口（Try Demo Mode）；010-B 九：i18n
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n";

export function Dashboard() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const nav = useNavigate();
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 3000 });
  const [goal, setGoal] = useState("");
  const [mode, setMode] = useState("fake");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [project, setProject] = useState("");

  const create = useMutation({
    mutationFn: (body: { goal: string; model_mode: string; project_alias?: string }) =>
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
      {/* New Task（010 八/二十三） */}
      <div className="card new-task">
        <input
          className="goal-input"
          placeholder={t("dash.placeholder")}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && goal.trim()) {
              create.mutate({ goal, model_mode: mode, project_alias: project || undefined });
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
              create.mutate({ goal, model_mode: mode, project_alias: project || undefined })
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
                  <span>{k}</span>
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
                <td>{tr.goal}</td>
                <td>
                  <StatusBadge status={tr.status} />
                </td>
                <td>{tr.model_mode}</td>
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
              <strong>{a.role}</strong>
              <StatusBadge status={a.status} />
              <span className="muted">{a.model}</span>
              <span className="muted">
                {a.tokens} {t("dash.tokenUnit")}
              </span>
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
