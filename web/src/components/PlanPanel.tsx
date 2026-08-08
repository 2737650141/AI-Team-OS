// Plan 面板（010 十一）：Planner 真实 Plan 的 Subtask 列表
import type { SubtaskView } from "../api/types";
import { useI18n } from "../i18n";
import { StatusBadge } from "./StatusBadge";

export function PlanPanel({ subtasks }: { subtasks: SubtaskView[] }) {
  const { t } = useI18n();
  return (
    <div className="plan">
      {subtasks.length === 0 && <p className="muted">{t("plan.empty")}</p>}
      {subtasks.map((s) => (
        <div key={s.subtask_id} className="plan-item">
          <span className="plan-id">{s.subtask_id}</span>
          <span className="plan-title">{s.title}</span>
          <span className="plan-role">{s.role}</span>
          <StatusBadge status={s.status} />
          <span className="plan-meta muted">
            deps: {s.dependencies.join(",") || "-"} · rework: {s.rework_count} · evidence:{" "}
            {s.evidence_refs.length}
          </span>
        </div>
      ))}
    </div>
  );
}
