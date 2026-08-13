import { CheckCircle2, CircleDot, ShieldAlert, XCircle } from "lucide-react";

import type { RuntimeEvent } from "../api/types";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";

const IMPORTANT: Record<string, "success" | "danger" | "warning"> = {
  approval_requested: "warning",
  approval_bypassed: "success",
  test_failed: "danger",
  task_failed: "danger",
  review_rejected: "danger",
  approval_rejected: "danger",
  rework_started: "warning",
  task_completed: "success",
  review_passed: "success",
  approval_approved: "success",
};

export function ActivityFeed({ events, presenting = false }: { events: RuntimeEvent[]; presenting?: boolean }) {
  const { lang, t } = useI18n();
  const visibleEvents = events.slice(-300);
  return (
    <div className="feed activity-feed">
      {events.length === 0 && <p className="muted">{t("feed.noActivity")}</p>}
      {visibleEvents.map((event) => {
        const tone = event.event_type === "test_completed" && Number(event.payload_safe.return_code ?? 0) !== 0
          ? "danger"
          : IMPORTANT[event.event_type];
        const payload = event.payload_safe ?? {};
        const subtask = String(payload.subtask_id ?? "");
        const modelDetail = event.event_type === "model_call_completed"
          ? `${String(payload.model ?? "")} · ${String(payload.total_tokens ?? "—")} tokens · ${String(payload.latency_ms ?? "—")}ms`
          : event.event_type === "model_call_started" ? String(payload.model ?? "") : "";
        return (
          <div key={event.event_id} className={`feed-item ${tone ? `feed-important ${tone}` : ""}`}>
            <span className="feed-icon">{tone === "danger" ? <XCircle size={15} /> : tone === "warning" ? <ShieldAlert size={15} /> : tone === "success" ? <CheckCircle2 size={15} /> : <CircleDot size={13} />}</span>
            <span className="feed-time">{formatTime(event.timestamp, lang)}</span>
            <span className="feed-actor">{displayLabel(event.actor_type ?? "system", lang)}</span>
            <span className="feed-type">{displayLabel(event.event_type, lang)}</span>
            {subtask && <span className="feed-context">{subtask}</span>}
            {modelDetail && <span className="feed-context">{modelDetail}</span>}
          </div>
        );
      })}
      {presenting && <div className="presentation-indicator"><span />{t("feed.presenting")}</div>}
    </div>
  );
}

function formatTime(value: string, lang: "zh" | "en") {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(lang === "zh" ? "zh-CN" : "en-US", { hour12: false });
}
