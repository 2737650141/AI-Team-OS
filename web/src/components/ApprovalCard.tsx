// 审批卡片（010 十二/十八）：Agent/Action/Risk/Files/Summary/Diff 引用/Approval/Reject
import { useState } from "react";

import { api } from "../api/client";
import type { ApprovalView } from "../api/types";
import { useI18n } from "../i18n";
import { StatusBadge } from "./StatusBadge";

export function ApprovalCard({
  approval,
  onDecision,
}: {
  approval: ApprovalView;
  onDecision: () => void;
}) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const decide = async (decision: "approve" | "reject") => {
    setBusy(true);
    setMsg("");
    try {
      await (decision === "approve"
        ? api.approve(approval.approval_id, reason || undefined)
        : api.reject(approval.approval_id, reason || undefined));
      setMsg(decision === "approve" ? t("ap.approved") : t("ap.rejected"));
      onDecision();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card approval-card">
      <div className="approval-head">
        <StatusBadge status={approval.status} />
        <strong>{approval.action_type}</strong>
        <span className={`risk risk-${approval.risk_level}`}>{approval.risk_level}</span>
      </div>
      <p className="muted">{approval.summary}</p>
      <div className="tags">
        {approval.target_paths.map((p) => (
          <code key={p}>{p}</code>
        ))}
      </div>
      {approval.status === "pending" && (
        <div className="approval-actions">
          <input
            type="text"
            placeholder={t("ap.reasonPlaceholder")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <button className="btn btn-danger" disabled={busy} onClick={() => decide("reject")}>
            {t("ap.reject")}
          </button>
          <button className="btn btn-primary" disabled={busy} onClick={() => decide("approve")}>
            {t("ap.approve")}
          </button>
        </div>
      )}
      {msg && <p className="msg">{msg}</p>}
    </div>
  );
}
