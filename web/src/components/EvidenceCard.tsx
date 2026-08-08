import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { EvidenceView } from "../api/types";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";

export function EvidenceCard({ evidence }: { evidence: EvidenceView }) {
  const { lang, t } = useI18n();
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: ["evidence-detail", evidence.evidence_id],
    queryFn: () => api.evidenceDetail(evidence.evidence_id),
    enabled: open && evidence.snapshot_status !== "missing",
    retry: false,
  });
  const claims = evidence.claims ?? [];
  const reliability = humanReliability(evidence.reliability, lang);
  const freshness = humanFreshness(evidence.freshness, evidence.retrieved_at ?? evidence.ts, lang);

  return (
    <article className="evidence-card product-evidence">
      <button className="evidence-summary" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <div>
          <strong>{evidence.title ?? evidence.tool ?? t("ev.evidenceItem")}</strong>
          <span>{evidence.summary || t("ev.noSummary")}</span>
        </div>
        <span className="evidence-toggle">{open ? "−" : "+"}</span>
      </button>
      <div className="evidence-meta-grid">
        <Meta label={t("ev.source")} value={displayLabel(evidence.source_uri ?? evidence.source ?? evidence.tool, lang)} />
        <Meta label={t("ev.retrieved")} value={formatDate(evidence.retrieved_at ?? evidence.ts, lang)} />
        <Meta label={t("ev.reliability")} value={reliability} />
        <Meta label={t("ev.freshness")} value={freshness} />
      </div>
      {open && (
        <div className="evidence-sections">
          <section>
            <h3>{t("ev.claims")}</h3>
            {claims.length ? claims.map((claim) => (
              <div className="claim-row" key={claim.claim_id ?? claim.text}>
                <p>{claim.text ?? claim.claim_id}</p>
                <span className="muted">
                  {t("ev.subtask")}: {claim.subtask_title ?? claim.subtask_id ?? evidence.subtask_title ?? "—"} · {t("ev.agent")}: {displayLabel(claim.agent ?? evidence.agent, lang)}
                </span>
              </div>
            )) : <p className="muted">{t("ev.noClaims")}</p>}
          </section>
          <section>
            <h3>{t("ev.integrity")}</h3>
            <dl className="detail-list">
              <div><dt>{t("ev.hash")}</dt><dd><code>{evidence.content_hash || detail.data?.content_hash || "—"}</code></dd></div>
              <div><dt>{t("ev.contentLength")}</dt><dd>{formatBytes(evidence.content_length ?? detail.data?.size ?? 0)}</dd></div>
              <div><dt>{t("ev.snapshotStatus")}</dt><dd>{snapshotLabel(evidence.snapshot_status, lang)}</dd></div>
            </dl>
          </section>
          <details className="metric-details">
            <summary>{t("ev.advancedMetrics")}</summary>
            <p className="muted">reliability: {evidence.reliability ?? "unknown"} · freshness: {evidence.freshness ?? "unknown"}</p>
          </details>
          <details className="raw-snapshot">
            <summary>{t("ev.rawSnapshot")}</summary>
            {(evidence.truncated || detail.data?.truncated_for_display) && <p className="truncation-notice">{t("ev.truncatedNotice")}</p>}
            {detail.isLoading && <p className="muted">{t("dash.loading")}</p>}
            {detail.isError && <p className="muted">{t("ev.snapshotUnavailable")}</p>}
            {detail.data && <pre className="json evidence-raw">{detail.data.snapshot}</pre>}
            {evidence.snapshot_status === "missing" && <p className="muted">{t("ev.snapshotUnavailable")}</p>}
          </details>
        </div>
      )}
    </article>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function humanReliability(value: string | number | null | undefined, lang: "zh" | "en") {
  const score = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(score)) return lang === "zh" ? "尚未评级" : "Not rated";
  if (score >= 0.8) return lang === "zh" ? "高可信" : "High confidence";
  if (score >= 0.6) return lang === "zh" ? "较可信" : "Good confidence";
  if (score >= 0.4) return lang === "zh" ? "需交叉验证" : "Needs verification";
  return lang === "zh" ? "低可信" : "Low confidence";
}

function humanFreshness(value: string | null | undefined, retrieved: string | undefined, lang: "zh" | "en") {
  const raw = (value ?? "").toLowerCase();
  if (["fresh", "current", "recent"].includes(raw)) return lang === "zh" ? "近期" : "Recent";
  if (["stale", "old"].includes(raw)) return lang === "zh" ? "可能过时" : "May be stale";
  const time = retrieved ? Date.parse(retrieved) : Number.NaN;
  if (Number.isFinite(time)) {
    const days = (Date.now() - time) / 86_400_000;
    if (days <= 7) return lang === "zh" ? "7 天内" : "Within 7 days";
    if (days <= 30) return lang === "zh" ? "30 天内" : "Within 30 days";
  }
  return lang === "zh" ? "时效未知" : "Freshness unknown";
}

function snapshotLabel(value: string | undefined, lang: "zh" | "en") {
  const labels: Record<string, [string, string]> = {
    available: ["快照完整", "Snapshot available"],
    truncated: ["受限快照", "Limited snapshot"],
    missing: ["快照不可用", "Snapshot unavailable"],
  };
  return (labels[value ?? "missing"] ?? labels.missing)[lang === "zh" ? 0 : 1];
}

function formatDate(value: string | undefined, lang: "zh" | "en") {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { hour12: false });
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}
