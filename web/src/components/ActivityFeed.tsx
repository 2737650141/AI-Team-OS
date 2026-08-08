// 活动流（010 十二）：结构化事件，只显示 Action/Tool/Decision/Status/Evidence/Result
import type { RuntimeEvent } from "../api/types";
import { useI18n } from "../i18n";

const ICON: Record<string, string> = {
  planner: "🧭",
  supervisor: "🎛️",
  researcher: "🔎",
  executor: "🛠️",
  reviewer: "✅",
  tool_gateway: "🔧",
  system: "⚙️",
  runner: "⚙️",
};

function time(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString("zh-CN", { hour12: false });
  } catch {
    return ts;
  }
}

export function ActivityFeed({ events }: { events: RuntimeEvent[] }) {
  const { t } = useI18n();
  return (
    <div className="feed">
      {events.length === 0 && <p className="muted">{t("feed.noActivity")}</p>}
      {events.map((ev) => (
        <div key={ev.event_id} className="feed-item">
          <span className="feed-time">{time(ev.timestamp)}</span>
          <span className="feed-actor">
            {ICON[ev.actor_type ?? ""] ?? "•"} {ev.actor_type ?? "system"}
          </span>
          <span className="feed-type">{ev.event_type}</span>
          <span className="feed-summary">{ev.summary}</span>
        </div>
      ))}
    </div>
  );
}
