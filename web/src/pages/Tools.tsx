// Tools（010 二十三）
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n";

export function Tools() {
  const { t } = useI18n();
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.tools });
  return (
    <div className="page">
      <h1>{t("tools.title")}</h1>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>{t("tools.name")}</th>
              <th>{t("tools.description")}</th>
              <th>{t("tools.risk")}</th>
              <th>{t("tools.readOnly")}</th>
            </tr>
          </thead>
          <tbody>
            {(tools.data ?? []).map((tool) => (
              <tr key={tool.name}>
                <td>
                  <code>{tool.name}</code>
                </td>
                <td>{tool.description}</td>
                <td>
                  <StatusBadge status={(tool.risk_level ?? "low").toLowerCase()} />
                </td>
                <td>{tool.read_only ? "yes" : "no"}</td>
              </tr>
            ))}
            {(tools.data ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  {t("tools.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
