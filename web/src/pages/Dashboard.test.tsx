// Dashboard 组件测试（010 四十八：Dashboard / Task creation / Secret form）
// i18n 默认中文（010-B 九）：断言使用中文文案
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { I18nProvider } from "../i18n";
import { Dashboard } from "./Dashboard";

const qc = () =>
  new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

function renderDashboard() {
  return render(
    <QueryClientProvider client={qc()}>
      <I18nProvider>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </I18nProvider>
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
    // 等待数据渲染（health 值经 StatusBadge 翻译为中文）
    await waitFor(() => expect(screen.getByText("进行中")).toBeInTheDocument());
    expect(screen.getByText("系统健康")).toBeInTheDocument();
    expect(screen.getAllByText("在线").length).toBeGreaterThan(0);
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
      screen.getByPlaceholderText("你想让 AI 团队做什么？"),
      "hello world",
    );
    await userEvent.click(screen.getByText("高级"));
    await userEvent.click(screen.getByRole("button", { name: "最高权限（免审批）" }));
    await userEvent.click(screen.getByRole("button", { name: "开始任务" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({
      goal: "hello world",
      model_mode: "fake",
      permission_mode: "full_access",
    })));
  });
});
