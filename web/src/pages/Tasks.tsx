// Tasks 列表（010 九）
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";

export function Tasks() {
  const nav = useNavigate();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks, refetchInterval: 3000 });
  return (
    <div className="page">
      <h1>Tasks</h1>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Goal</th>
              <th>Status</th>
              <th>Mode</th>
              <th>Tokens</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {(tasks.data ?? []).map((t) => (
              <tr key={t.run_id} className="clickable" onClick={() => nav(`/tasks/${t.run_id}`)}>
                <td>
                  <code>{t.run_id}</code>
                </td>
                <td>{t.goal}</td>
                <td>
                  <StatusBadge status={t.status} />
                </td>
                <td>{t.model_mode}</td>
                <td>{t.tokens}</td>
                <td>${t.cost.toFixed(4)}</td>
              </tr>
            ))}
            {(tasks.data ?? []).length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No tasks yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
