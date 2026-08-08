import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { I18nProvider } from "../i18n";
import { ActivityFeed } from "./ActivityFeed";
import { DiffViewer } from "./DiffViewer";
import { EvidenceCard } from "./EvidenceCard";

const wrap = (node: React.ReactNode) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <I18nProvider>{node}</I18nProvider>
  </QueryClientProvider>,
);

afterEach(() => vi.restoreAllMocks());

describe("UI-02 product polish", () => {
  it("renders changed-file navigation, real hunk line numbers, and split controls", () => {
    wrap(<DiffViewer diff={"--- a/calc.py\n+++ b/calc.py\n@@ -10,2 +10,2 @@\n-old\n+new\n context"} files={[{ path: "calc.py", status: "M" }]} />);
    expect(screen.getByText("变更文件")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /M calc.py/ })).toBeInTheDocument();
    expect(screen.getByText("同步滚动")).toBeInTheDocument();
    expect(screen.getAllByText("10").length).toBeGreaterThan(0);
    expect(screen.getAllByText("11").length).toBeGreaterThan(0);
  });

  it("shows human evidence terms and keeps raw snapshot collapsed", async () => {
    vi.spyOn(api, "evidenceDetail").mockResolvedValue({ evidence_id: "abc", snapshot: "raw", snapshot_ref: "evidence/abc.txt", size: 3, content_hash: "hash", truncated_for_display: false });
    wrap(<EvidenceCard evidence={{ evidence_id: "abc", title: "Fixture source", summary: "Verified source", source_uri: "fixture", retrieved_at: new Date().toISOString(), reliability: "0.7", freshness: "recent", content_hash: "hash", content_length: 3, snapshot_status: "available", claims: [{ claim_id: "c1", text: "A verified claim", subtask_title: "Research", agent: "researcher" }] }} />);
    expect(screen.getByText("较可信")).toBeInTheDocument();
    expect(screen.getByText("近期")).toBeInTheDocument();
    expect(screen.queryByText("Raw Snapshot")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Fixture source/ }));
    expect(screen.getByText("原始快照")).toBeInTheDocument();
    expect(screen.getByText("A verified claim")).toBeInTheDocument();
  });

  it("maps internal event enums to user-facing labels", () => {
    wrap(<ActivityFeed events={[{ event_id: "e1", task_id: "t1", run_id: "r1", timestamp: new Date().toISOString(), sequence: 1, event_type: "approval_requested", actor_type: "executor", actor_id: "executor", summary: "approval requested", payload_safe: { subtask_id: "s1" } }]} />);
    expect(screen.getByText("需要审批")).toBeInTheDocument();
    expect(screen.getByText("执行员")).toBeInTheDocument();
    expect(screen.queryByText("approval_requested")).not.toBeInTheDocument();
  });
});
