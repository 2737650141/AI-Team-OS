// Evidence（010 二十一）
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";

export function Evidence() {
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const firstRun = (tasks.data ?? [])[0]?.run_id;
  const evidence = useQuery({
    queryKey: ["evidence", firstRun],
    queryFn: () => api.evidence(firstRun!),
    enabled: !!firstRun,
  });
  return (
    <div className="page">
      <h1>Evidence</h1>
      <div className="card">
        {!firstRun && <p className="muted">No tasks yet.</p>}
        {(evidence.data ?? []).map((e) => (
          <details key={e.evidence_id} className="evidence-card">
            <summary>
              <code>{e.evidence_id}</code> · {e.title}
            </summary>
            <div className="evidence-detail muted">
              <div>source: {e.source}</div>
              <div>type: {e.source_type}</div>
              <div>reliability: {e.reliability}</div>
              <div>hash: <code>{e.hash}</code></div>
              <div>claims: {e.claims.length}</div>
            </div>
          </details>
        ))}
        {(evidence.data ?? []).length === 0 && firstRun && (
          <p className="muted">No evidence for the latest task.</p>
        )}
      </div>
    </div>
  );
}
