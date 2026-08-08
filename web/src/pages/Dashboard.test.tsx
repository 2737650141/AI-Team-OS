// Dashboard 组件测试（010 四十八：Dashboard / Task creation / Secret form）
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { Dashboard } from "./Dashboard";

const qc = () =>
  new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

function renderDashboard() {
  return render(
    <QueryClientProvider client={qc()}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Dashboard", () => {
  it("renders system health + metrics from API", async () => {
    vi.spyOn(api, "dashboard").mockResolvedValue({
      system: {
        backend: "Online", langgraph: "Online", sqlite: "Online", event_store: "Online",
        model_provider: "Blocked", github: "Missing", mcp: "Disabled", sandbox: "Disabled",
        network_isolation: "Best Effort",
      },
      metrics: {
        active_tasks: 1, completed_tasks: 2, failed_tasks: 0, pending_approvals: 1,
        evidence_count: 5, tool_calls: 12, tokens: 1000, cost: 0.01, event_count: 30,
      },
      recent_tasks: [],
      agent_team: [],
    });
    renderDashboard();
    // 等待数据渲染（health 值经 StatusBadge 转小写，多个 online 状态）
    await waitFor(() => expect(screen.getAllByText("online").length).toBeGreaterThan(0));
    expect(screen.getByText("System Health")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("creates a task and navigates to detail", async () => {
    vi.spyOn(api, "dashboard").mockResolvedValue({
      system: { backend: "Online", langgraph: "Online", sqlite: "Online", event_store: "Online",
        model_provider: "Blocked", github: "Missing", mcp: "Disabled", sandbox: "Disabled",
        network_isolation: "Best Effort" },
      metrics: { active_tasks: 0, completed_tasks: 0, failed_tasks: 0, pending_approvals: 0,
        evidence_count: 0, tool_calls: 0, tokens: 0, cost: 0, event_count: 0 },
      recent_tasks: [],
      agent_team: [],
    });
    const create = vi
      .spyOn(api, "createTask")
      .mockResolvedValue({ run_id: "run123", task_id: "t1", status: "paused" });
    renderDashboard();
    await userEvent.type(
      screen.getByPlaceholderText("What do you want the AI team to do?"),
      "hello world",
    );
    await userEvent.click(screen.getByRole("button", { name: "Start Task" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({ goal: "hello world", model_mode: "fake" })));
  });
});
