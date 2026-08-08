// Agents（010 二十二，只读）
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";

export function Agents() {
  const { lang, t } = useI18n();
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  return (
    <div className="page">
      <h1>{t("agents.title")}</h1>
      <div className="agent-grid">
        {(agents.data ?? []).map((a) => (
          <div key={a.agent_id} className="card agent-card">
            <div className="agent-head">
              <strong>{displayLabel(a.role, lang)}</strong>
              <StatusBadge status={a.enabled ? (a.status ?? "idle") : "disabled"} />
            </div>
            <span className="muted">{t("agents.model")}: {a.model}</span>
            <div className="agent-presence-grid">
              <Presence label={t("agents.currentAction")} value={displayLabel(a.current_action ?? a.status, lang)} />
              <Presence label={t("agents.currentSubtask")} value={a.current_subtask ?? "—"} />
              <Presence label={t("agents.latestCompleted")} value={a.latest_completed ?? "—"} />
            </div>
            {a.current_task && <span className="muted">{t("agents.currentTask")}: {displayLabel(a.current_task, lang)}</span>}
            <span className="muted">{t("agents.capacity")}: {a.token_limit} Token · {a.allowed_tools.length} {t("agents.tools")}</span>
            <details>
              <summary>{t("agents.allowedTools")}</summary>
              <ul>
                {a.allowed_tools.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </details>
          </div>
        ))}
      </div>
    </div>
  );
}

function Presence({ label, value }: { label: string; value: string }) {
  return <span><small>{label}</small><strong>{value}</strong></span>;
}
