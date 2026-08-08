// Tools（010 二十三）
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";

export function Tools() {
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.tools });
  return (
    <div className="page">
      <h1>Tools</h1>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Description</th>
              <th>Risk</th>
              <th>Read Only</th>
            </tr>
          </thead>
          <tbody>
            {(tools.data ?? []).map((t) => (
              <tr key={t.name}>
                <td>
                  <code>{t.name}</code>
                </td>
                <td>{t.description}</td>
                <td>
                  <StatusBadge status={(t.risk_level ?? "low").toLowerCase()} />
                </td>
                <td>{t.read_only ? "yes" : "no"}</td>
              </tr>
            ))}
            {(tools.data ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  No tools registered.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
