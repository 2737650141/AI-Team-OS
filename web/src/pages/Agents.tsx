// Agents（010 二十二，只读）
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";

export function Agents() {
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  return (
    <div className="page">
      <h1>Agents</h1>
      <div className="agent-grid">
        {(agents.data ?? []).map((a) => (
          <div key={a.agent_id} className="card agent-card">
            <div className="agent-head">
              <strong>{a.display_name}</strong>
              <StatusBadge status={a.enabled ? "idle" : "disabled"} />
            </div>
            <span className="muted">model: {a.model}</span>
            <span className="muted">
              token limit: {a.token_limit} · tools: {a.allowed_tools.length}
            </span>
            <details>
              <summary>Allowed tools</summary>
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
