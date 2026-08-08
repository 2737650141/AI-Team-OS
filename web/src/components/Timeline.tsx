// 工作流时间线（010 十部分）：Goal→Clarification→Planning→Research→Execution→Approval→Testing→Review→Completed
import { useI18n } from "../i18n";

function stageState(index: number, status: string): string {
  if (status === "completed" || status === "passed") return "done";
  if (status === "failed" || status === "rejected") return "fail";
  const cur = statusToIndex(status);
  if (cur === index) return "active";
  if (index < cur) return "done";
  return "todo";
}

function statusToIndex(status: string): number {
  switch (status) {
    case "paused":
    case "waiting_approval":
      return 5; // approval
    case "running":
    case "planning":
    case "executing":
      return 2;
    default:
      return 0;
  }
}

export function Timeline({ status }: { status: string }) {
  const { t } = useI18n();
  const STAGES = [
    { id: "goal", label: t("tl.goal") },
    { id: "clarification", label: t("tl.clarification") },
    { id: "planning", label: t("tl.planning") },
    { id: "research", label: t("tl.research") },
    { id: "execution", label: t("tl.execution") },
    { id: "approval", label: t("tl.approval") },
    { id: "testing", label: t("tl.testing") },
    { id: "review", label: t("tl.review") },
    { id: "completed", label: t("tl.completed") },
  ];
  return (
    <div className="timeline">
      {STAGES.map((s, i) => {
        const st = stageState(i, status);
        return (
          <div key={s.id} className={`tl-step ${st}`}>
            <span className="tl-dot" />
            <span className="tl-label">{s.label}</span>
          </div>
        );
      })}
    </div>
  );
}
