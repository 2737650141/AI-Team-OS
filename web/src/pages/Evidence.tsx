import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { EvidenceCard } from "../components/EvidenceCard";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";

export function Evidence() {
  const { lang, t } = useI18n();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const [selectedRun, setSelectedRun] = useState("");
  const runId = selectedRun || (tasks.data ?? [])[0]?.run_id || "";
  const evidence = useQuery({
    queryKey: ["evidence", runId],
    queryFn: () => api.evidence(runId),
    enabled: !!runId,
  });
  return (
    <div className="page evidence-page">
      <div className="page-heading">
        <div>
          <h1>{t("ev.title")}</h1>
          <p className="muted">{t("ev.intro")}</p>
        </div>
        {(tasks.data ?? []).length > 0 && (
          <select aria-label={t("ev.chooseTask")} value={runId} onChange={(event) => setSelectedRun(event.target.value)}>
            {(tasks.data ?? []).slice(0, 50).map((task) => (
              <option key={task.run_id} value={task.run_id}>
                {displayLabel(task.goal, lang)} · {task.run_id.slice(0, 8)}
              </option>
            ))}
          </select>
        )}
      </div>
      {!runId && <div className="card"><p className="muted">{t("ev.noTasks")}</p></div>}
      {(evidence.data ?? []).map((item) => <EvidenceCard key={item.evidence_id} evidence={item} />)}
      {runId && !evidence.isLoading && (evidence.data ?? []).length === 0 && <div className="card"><p className="muted">{t("ev.noEvidence")}</p></div>}
    </div>
  );
}
