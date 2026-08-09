import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { ComputerStatus } from "../api/types";
import { I18nProvider } from "../i18n";
import { Computer } from "./Computer";

function renderComputer() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider>
        <Computer />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const inactive: ComputerStatus = {
  session: null,
  screen_access: false,
  control: "off",
  jarvis_status: "idle",
  windows: [],
  current_task: null,
  pending_actions: [],
  recent_actions: [],
  safety_status: { default_control: "off", credential_fields: "forbidden" },
};

const active: ComputerStatus = {
  ...inactive,
  session: {
    session_id: "session-1",
    started_at: "2026-08-10T00:00:00Z",
    expires_at: "2026-08-10T00:15:00Z",
    status: "active",
    capability: "low_risk_control",
    action_count: 2,
  },
  screen_access: true,
  control: "on",
  active_window: {
    window_id: "hwnd:1",
    title: "Untitled - Notepad",
    app_name: "Notepad",
    bounds: { left: 0, top: 0, right: 800, bottom: 600 },
    is_active: true,
    window_hash: "window-1",
  },
  windows: [],
  current_task: {
    task_id: "win-1",
    goal: "open notepad",
    status: "waiting_approval",
    created_at: "2026-08-10T00:00:00Z",
    model_mode: "real",
    provider: "DeepSeek Official",
    model: "deepseek-v4-flash",
    real_call: true,
    planner_recovered: false,
    replan_count: 0,
    action_plan: [
      {
        step_id: "step-1",
        tool: "windows_launch_app",
        arguments: { app_id: "notepad" },
        rationale: "打开注册应用",
        expected_state: "窗口出现",
        risk: "low",
        status: "completed",
      },
    ],
    current_step: 1,
    result: "",
    memory_preference_applied: true,
    token_usage: {},
  },
  pending_actions: [
    {
      approval_id: "approval-1",
      task_id: "win-1",
      step_id: "step-2",
      tool: "windows_set_text",
      risk: "medium",
      summary: "输入测试文字",
      arguments_display: { characters: 8 },
      status: "pending",
    },
  ],
  recent_actions: [
    {
      action_id: "action-1",
      timestamp: "2026-08-10T00:00:01Z",
      tool: "windows_launch_app",
      risk: "low",
      status: "completed",
      summary: "Launched registered app notepad",
      verification: "application window exists",
      retry_count: 0,
    },
  ],
};

beforeEach(() => {
  localStorage.setItem("ai-team-os-lang", "zh");
  vi.restoreAllMocks();
});

describe("Computer", () => {
  it("defaults to off and offers only bounded session capabilities", async () => {
    vi.spyOn(api, "computer").mockResolvedValue(inactive);
    const start = vi.spyOn(api, "startComputer").mockResolvedValue(active);
    renderComputer();

    await screen.findByText("电脑控制当前关闭。AI Team OS 无权观察或操作桌面。");
    expect(screen.getAllByText("OFF").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("option", { name: "仅观察" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "低风险控制" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "每个动作前询问" })).toBeInTheDocument();
    expect(screen.queryByText(/unlimited|无限最高权限/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "开始控制" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("observe_only"));
  });

  it("shows real identity, plan, approval, history and emergency stop", async () => {
    vi.spyOn(api, "computer").mockResolvedValue(active);
    const stop = vi.spyOn(api, "stopComputer").mockResolvedValue(inactive);
    renderComputer();

    await screen.findByText("DeepSeek Official");
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.getByText("已应用偏好：控制电脑前先显示操作计划")).toBeInTheDocument();
    expect(screen.getByText("输入测试文字")).toBeInTheDocument();
    expect(screen.getByText("Launched registered app notepad")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "立即停止控制" }).length).toBeGreaterThan(0);

    await userEvent.click(screen.getAllByRole("button", { name: "立即停止控制" })[0]);
    await waitFor(() => expect(stop).toHaveBeenCalledTimes(1));
  });
});
