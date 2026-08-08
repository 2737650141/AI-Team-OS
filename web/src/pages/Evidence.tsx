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
              <code>{e.evidence_id}</code> · {e.title}
            </summary>
            <div className="evidence-detail muted">
              <div>source: {e.source}</div>
              <div>type: {e.source_type}</div>
              <div>{t("ev.reliability")}: {e.reliability}</div>
              <div>{t("ev.hash")}: <code>{e.hash}</code></div>
              <div>claims: {e.claims.length}</div>
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
