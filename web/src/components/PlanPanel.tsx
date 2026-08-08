// Plan 面板（010 十一）：Planner 真实 Plan 的 Subtask 列表
import type { SubtaskView } from "../api/types";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";
import { StatusBadge } from "./StatusBadge";

export function PlanPanel({ subtasks }: { subtasks: SubtaskView[] }) {
  const { lang, t } = useI18n();
  return (
    <div className="plan">
      {subtasks.length === 0 && <p className="muted">{t("plan.empty")}</p>}
      {subtasks.map((s) => (
        <div key={s.subtask_id} className="plan-item">
          <span className="plan-id">{s.subtask_id}</span>
          <span className="plan-title">{s.title}</span>
          <span className="plan-role">{displayLabel(s.role, lang)}</span>
          <StatusBadge status={s.status} />
          <span className="plan-meta muted">
            {t("plan.dependencies")}: {s.dependencies.join(",") || "-"} · {t("plan.rework")}: {s.rework_count} · {t("plan.evidence")}:{" "}
            {s.evidence_refs.length}
          </span>
        </div>
      ))}
    </div>
  );
}
