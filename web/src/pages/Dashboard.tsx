// Dashboard（010 七/八）：System Health + Metrics + New Task + Recent Tasks + Agent Team
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";

export function Dashboard() {
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
      <h1>Dashboard</h1>
      {/* New Task（010 八/二十三） */}
      <div className="card new-task">
        <input
          className="goal-input"
          placeholder="What do you want the AI team to do?"
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
              Demo
            </button>
            <button className={mode === "real" ? "on" : ""} onClick={() => setMode("real")}>
              Real
            </button>
          </label>
          <button
            className="btn btn-primary"
            disabled={!goal.trim() || create.isPending}
            onClick={() =>
              create.mutate({ goal, model_mode: mode, project_alias: project || undefined })
            }
          >
            Start Task
          </button>
        </div>
        <details open={showAdvanced} onToggle={(e) => setShowAdvanced(e.currentTarget.open)}>
          <summary>Advanced</summary>
          <label className="field">
            Project
            <input value={project} onChange={(e) => setProject(e.target.value)} placeholder="sample-python" />
          </label>
        </details>
        {create.isError && <p className="error">{(create.error as Error).message}</p>}
      </div>

      {/* System Health（010 八） */}
      <div className="card">
        <h2>System Health</h2>
        <div className="health-grid">
          {data
            ? Object.entries(data.system).map(([k, v]) => (
                <div key={k} className="health-item">
                  <span>{k}</span>
                  <StatusBadge status={v.toLowerCase()} />
                </div>
              ))
            : "Loading…"}
        </div>
      </div>

      {/* Metrics（010 八） */}
      <div className="card">
        <h2>Metrics</h2>
        {data && (
          <div className="metrics-grid">
            <Metric label="Active" value={data.metrics.active_tasks} />
            <Metric label="Completed" value={data.metrics.completed_tasks} />
            <Metric label="Failed" value={data.metrics.failed_tasks} />
            <Metric label="Pending Approvals" value={data.metrics.pending_approvals} />
            <Metric label="Evidence" value={data.metrics.evidence_count} />
            <Metric label="Tool Calls" value={data.metrics.tool_calls} />
            <Metric label="Tokens" value={data.metrics.tokens} />
            <Metric label="Cost" value={`$${data.metrics.cost.toFixed(4)}`} />
          </div>
        )}
      </div>

      {/* Recent Tasks（010 八） */}
      <div className="card">
        <h2>Recent Tasks</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Goal</th>
              <th>Status</th>
              <th>Model</th>
              <th>Tokens</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {(data?.recent_tasks ?? []).map((t) => (
              <tr key={t.run_id} onClick={() => nav(`/tasks/${t.run_id}`)} className="clickable">
                <td>{t.goal}</td>
                <td>
                  <StatusBadge status={t.status} />
                </td>
                <td>{t.model_mode}</td>
                <td>{t.tokens}</td>
                <td>${t.cost.toFixed(4)}</td>
              </tr>
            ))}
            {(data?.recent_tasks ?? []).length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No tasks yet — try the demo.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Agent Team（010 八） */}
      <div className="card">
        <h2>Agent Team</h2>
        <div className="agent-grid">
          {(data?.agent_team ?? []).map((a) => (
            <div key={a.role} className="agent-card">
              <strong>{a.role}</strong>
              <StatusBadge status={a.status} />
              <span className="muted">{a.model}</span>
              <span className="muted">{a.tokens} tokens</span>
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
