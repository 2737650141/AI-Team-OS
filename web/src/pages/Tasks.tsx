// Tasks 列表（010 九）
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n";

export function Tasks() {
  const { t } = useI18n();
  const nav = useNavigate();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks, refetchInterval: 3000 });
  return (
    <div className="page">
      <h1>{t("tasksPage.title")}</h1>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>{t("tasksPage.runId")}</th>
              <th>{t("tasksPage.goal")}</th>
              <th>{t("tasksPage.status")}</th>
              <th>{t("tasksPage.mode")}</th>
              <th>{t("tasksPage.tokens")}</th>
              <th>{t("tasksPage.cost")}</th>
            </tr>
          </thead>
          <tbody>
            {(tasks.data ?? []).map((tr) => (
              <tr key={tr.run_id} className="clickable" onClick={() => nav(`/tasks/${tr.run_id}`)}>
                <td>
                  <code>{tr.run_id}</code>
                </td>
                <td>{tr.goal}</td>
                <td>
                  <StatusBadge status={tr.status} />
                </td>
                <td>{tr.model_mode}</td>
                <td>{tr.tokens}</td>
                <td>${tr.cost.toFixed(4)}</td>
              </tr>
            ))}
            {(tasks.data ?? []).length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  {t("dash.noTasks")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
