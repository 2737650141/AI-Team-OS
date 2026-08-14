import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { JarvisNotifications } from "./JarvisNotifications";

let actionCallback: ((notification: { extra?: Record<string, unknown> }) => void) | undefined;
const sendNotification = vi.fn();

vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn().mockResolvedValue(true),
  requestPermission: vi.fn().mockResolvedValue("granted"),
  sendNotification,
  onAction: vi.fn(async (callback) => {
    actionCallback = callback;
    return { unregister: vi.fn() };
  }),
}));

beforeEach(() => {
  vi.restoreAllMocks();
  sendNotification.mockClear();
  actionCallback = undefined;
  window.localStorage.clear();
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  vi.spyOn(api, "interactionSettings").mockResolvedValue({ mode: "normal", notify_completed: true, notify_approval: true, notify_failed: true, changed_at: "" });
  vi.spyOn(api, "dashboard").mockResolvedValue({ system: {} as never, metrics: { active_tasks: 0, completed_tasks: 1, failed_tasks: 0, pending_approvals: 0, evidence_count: 0, tool_calls: 0, tokens: 10, cost: 0, event_count: 1 }, recent_tasks: [{ task_id: "task-1", run_id: "run-1", status: "completed", run_kind: "user_task", goal: "研究项目", project_id: "default", model_mode: "real", tokens: 10, cost: 0, tool_calls: 0, started_at: null, duration_s: 2 }], agent_team: [] });
});

it("sends one desktop notification and returns clicks to the original run", async () => {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><JarvisNotifications /></MemoryRouter></QueryClientProvider>);
  await waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
  actionCallback?.({ extra: { run_id: "run-1" } });
  expect(window.localStorage.getItem("ai-team-os.jarvis-focus-run")).toBe("run-1");
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(sendNotification).toHaveBeenCalledTimes(1);
});
