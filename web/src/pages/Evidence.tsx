// Evidence（010 二十一）
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { useI18n } from "../i18n";

export function Evidence() {
  const { t } = useI18n();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const firstRun = (tasks.data ?? [])[0]?.run_id;
  const evidence = useQuery({
    queryKey: ["evidence", firstRun],
    queryFn: () => api.evidence(firstRun!),
    enabled: !!firstRun,
  });
  return (
    <div className="page">
      <h1>{t("ev.title")}</h1>
      <div className="card">
        {!firstRun && <p className="muted">{t("ev.noTasks")}</p>}
        {(evidence.data ?? []).map((e) => (
          <details key={e.evidence_id} className="evidence-card">
            <summary>
              <code>{e.evidence_id}</code> · {e.title ?? e.summary ?? e.tool ?? "Evidence"}
            </summary>
            <div className="evidence-detail muted">
              <div>source: {e.source ?? e.source_uri ?? e.tool ?? "—"}</div>
              <div>type: {e.source_type ?? e.tool ?? "—"}</div>
              <div>{t("ev.reliability")}: {e.reliability ?? "recorded"}</div>
              <div>{t("ev.hash")}: <code>{e.hash ?? "—"}</code></div>
              <div>claims: {e.claims?.length ?? 0}</div>
              <div>retrieved: {e.retrieved_at ?? e.ts ?? "—"}</div>
            </div>
          </details>
        ))}
        {(evidence.data ?? []).length === 0 && firstRun && (
          <p className="muted">{t("ev.noEvidence")}</p>
        )}
      </div>
    </div>
  );
}
