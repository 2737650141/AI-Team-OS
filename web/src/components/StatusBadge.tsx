// 状态徽章（010 十：gray/blue/yellow/green/red）；显示文案随语言切换（010-B 九）
import { useI18n } from "../i18n";

const MAP: Record<string, string> = {
  pending: "badge-gray",
  running: "badge-blue",
  planning: "badge-blue",
  executing: "badge-blue",
  paused: "badge-yellow",
  waiting: "badge-yellow",
  waiting_approval: "badge-yellow",
  completed: "badge-green",
  active: "badge-green",
  passed: "badge-green",
  idle: "badge-green",
  failed: "badge-red",
  rejected: "badge-red",
  forgotten: "badge-gray",
  expired: "badge-gray",
  superseded: "badge-yellow",
  cancelled: "badge-gray",
  error: "badge-red",
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const label = t(`st.${status}`);
  return <span className={`badge ${MAP[status] ?? "badge-gray"}`}>{label === `st.${status}` ? status : label}</span>;
}
