// 工作流时间线（010 十部分）：Goal→Clarification→Planning→Research→Execution→Approval→Testing→Review→Completed
const STAGES = [
  { id: "goal", label: "Goal" },
  { id: "clarification", label: "Clarification" },
  { id: "planning", label: "Planning" },
  { id: "research", label: "Research" },
  { id: "execution", label: "Execution" },
  { id: "approval", label: "Approval" },
  { id: "testing", label: "Testing" },
  { id: "review", label: "Review" },
  { id: "completed", label: "Completed" },
];

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
