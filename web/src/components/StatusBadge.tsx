// 状态徽章（010 十：gray/blue/yellow/green/red）
const MAP: Record<string, string> = {
  pending: "badge-gray",
  running: "badge-blue",
  planning: "badge-blue",
  executing: "badge-blue",
  paused: "badge-yellow",
  waiting: "badge-yellow",
  waiting_approval: "badge-yellow",
  completed: "badge-green",
  passed: "badge-green",
  idle: "badge-green",
  failed: "badge-red",
  rejected: "badge-red",
  error: "badge-red",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${MAP[status] ?? "badge-gray"}`}>{status}</span>;
}
