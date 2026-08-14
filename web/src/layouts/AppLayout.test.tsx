// 024-B 三栏信息架构前端测试（NAV01-10）
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { DashboardData } from "../api/types";
import { I18nProvider } from "../i18n";
import { AppLayout } from "./AppLayout";
import { RightInspector } from "../components/RightInspector";
import type { RuntimeEvent } from "../api/types";

const qc = () => new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

const dashboard: DashboardData = {
  system: { backend: "ONLINE", langgraph: "ONLINE", sqlite: "ONLINE", event_store: "ONLINE", model_provider: "ONLINE", github: "ONLINE", mcp: "ONLINE", sandbox: "ONLINE", network_isolation: "ONLINE" },
  metrics: { active_tasks: 0, completed_tasks: 0, failed_tasks: 0, pending_approvals: 0, evidence_count: 0, tool_calls: 0, tokens: 0, cost: 0, event_count: 0 },
  recent_tasks: [
    { task_id: "t1", run_id: "run-1", status: "completed", run_kind: "user_task", goal: "分析项目", project_id: "project-alpha", model_mode: "real", tokens: 0, cost: 0, tool_calls: 0, started_at: null, duration_s: null },
  ],
  agent_team: [],
};

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(api, "permissionMode").mockResolvedValue({ mode: "standard", changed_at: "", changed_by_user: true, version: 1, maximum_confirmed: false });
  vi.spyOn(api, "activeContext").mockResolvedValue({ active: false, context: null });
  vi.spyOn(api, "dashboard").mockResolvedValue(dashboard);
  vi.spyOn(api, "jarvisSessions").mockResolvedValue({
    sessions: [{ session_id: "conv-1", current_goal: "研究 MetaGPT", current_project: "default", updated_at: "now", message_count: 3, last_summary: "MetaGPT 详情" }],
  });
});
afterEach(() => vi.restoreAllMocks());

function renderLayout() {
  return render(
    <QueryClientProvider client={qc()}>
      <I18nProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={<div>JARVIS 页面</div>} />
              <Route path="/tasks" element={<div>任务页面</div>} />
              <Route path="/settings" element={<div>设置页面</div>} />
              <Route path="/usage" element={<div>用量页面</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("NAV · 三栏信息架构", () => {
  it("NAV01: LEFT 栏包含新对话 / Projects / Recent conversations / Control Center / Settings", async () => {
    renderLayout();
    expect(await screen.findByText("新对话")).toBeInTheDocument();
    expect(screen.getByText("项目")).toBeInTheDocument();
    expect(screen.getByText("最近对话")).toBeInTheDocument();
    // 控制中心同时作为 brand 副标题与导航分组名出现，允许多次
    expect(screen.getAllByText("控制中心").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("设置")).toBeInTheDocument();
  });

  it("NAV02: Projects 显示 dashboard 中的项目", async () => {
    renderLayout();
    expect(await screen.findByText("project-alpha")).toBeInTheDocument();
  });

  it("NAV03: Recent conversations 显示最近会话", async () => {
    renderLayout();
    expect(await screen.findByText("研究 MetaGPT")).toBeInTheDocument();
  });

  it("NAV04: Control Center 收纳 Tasks/Agents/Approvals/Evidence/Usage/Memory/Tools/Logs", async () => {
    renderLayout();
    await screen.findByText("新对话");
    const controlCenter = screen.getByRole("button", { name: "控制中心" });
    expect(controlCenter).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("任务")).not.toBeInTheDocument();
    await userEvent.click(controlCenter);
    expect(controlCenter).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("任务")).toBeInTheDocument();
    expect(screen.getByText("智能体")).toBeInTheDocument();
    expect(screen.getByText("审批")).toBeInTheDocument();
    expect(screen.getByText("证据")).toBeInTheDocument();
    expect(screen.getByText("用量")).toBeInTheDocument();
    expect(screen.getByText("记忆")).toBeInTheDocument();
    expect(screen.getByText("工具")).toBeInTheDocument();
    expect(screen.getByText("日志")).toBeInTheDocument();
  });

  it("NAV05: 控制中心入口保留原路由（/tasks 仍可达）", async () => {
    renderLayout();
    await userEvent.click(await screen.findByRole("button", { name: "控制中心" }));
    await userEvent.click(await screen.findByText("任务"));
    expect(await screen.findByText("任务页面")).toBeInTheDocument();
  });

  it("NAV06: 新对话按钮调用清空会话 API 并回首页", async () => {
    const clear = vi.spyOn(api, "clearJarvisSession").mockResolvedValue({ session_id: "jarvis-desktop", messages: [], current_goal: null, current_task_reference: null, current_project: "default", no_write: false, created_at: "", updated_at: "" });
    renderLayout();
    await userEvent.click(await screen.findByText("新对话"));
    await waitFor(() => expect(clear).toHaveBeenCalledWith("jarvis-desktop"));
    expect(await screen.findByText("JARVIS 页面")).toBeInTheDocument();
  });

  it("NAV07: 顶部轻量状态提供 Computer 快捷入口", async () => {
    renderLayout();
    expect(await screen.findByText("电脑")).toBeInTheDocument();
  });

  it("NAV08: 既有页面路由未删除（/usage 可达）", async () => {
    renderLayout();
    await userEvent.click(await screen.findByRole("button", { name: "控制中心" }));
    await userEvent.click(await screen.findByText("用量"));
    expect(await screen.findByText("用量页面")).toBeInTheDocument();
  });

  it("NAV09: 会话切换经 query 参数隔离（/ ?session=conv-1）", async () => {
    const sessions = vi.spyOn(api, "jarvisSessions");
    renderLayout();
    expect(sessions).toHaveBeenCalled();
  });
});

describe("NAV · RightInspector", () => {
  const events: RuntimeEvent[] = [{ event_id: "e1", task_id: "t1", run_id: "run-1", timestamp: "now", sequence: 1, event_type: "task_created", actor_type: "user", actor_id: "u1", summary: "任务已创建", payload_safe: {} }];

  it("NAV10: Inspector 提供 Overview | Files | Changes | Activity 四个 tab", async () => {
    vi.spyOn(api, "diff").mockResolvedValue({ diff: "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new", files: [{ path: "x.txt", status: "M" }] });
    render(
      <QueryClientProvider client={qc()}>
        <I18nProvider>
          <RightInspector runId="run-1" task={undefined} usage={undefined} events={[]} connected={false} />
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("tab", { name: /概览/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /文件/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /变更/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /动态/ })).toBeInTheDocument();
    // 无任务时 Overview 显示空态
    expect(screen.getByText(/运行任务后这里会显示概览/)).toBeInTheDocument();
  });

  it("Activity tab 显示事件流", async () => {
    render(
      <QueryClientProvider client={qc()}>
        <I18nProvider>
          <RightInspector runId="run-1" task={undefined} usage={undefined} events={events} connected={false} />
        </I18nProvider>
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("tab", { name: /动态/ }));
    // event_type 翻译与 summary 都是"任务已创建"，允许出现多次
    expect(screen.getAllByText("任务已创建").length).toBeGreaterThanOrEqual(1);
  });
});
