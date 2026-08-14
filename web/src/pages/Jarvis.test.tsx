import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { DashboardData, JarvisSession, TaskDetail, UsageSummary } from "../api/types";
import { I18nProvider } from "../i18n";
import { Jarvis } from "./Jarvis";

const emptySession: JarvisSession = {
  session_id: "jarvis-test",
  messages: [],
  current_goal: null,
  current_task_reference: null,
  current_project: "default",
  no_write: false,
  created_at: "2026-08-14T00:00:00",
  updated_at: "2026-08-14T00:00:00",
};

const dashboard: DashboardData = {
  system: { backend: "ONLINE", langgraph: "ONLINE", sqlite: "ONLINE", event_store: "ONLINE", model_provider: "ONLINE", github: "ONLINE", mcp: "ONLINE", sandbox: "ONLINE", network_isolation: "ONLINE" },
  metrics: { active_tasks: 0, completed_tasks: 0, failed_tasks: 0, pending_approvals: 0, evidence_count: 0, tool_calls: 0, tokens: 0, cost: 0, event_count: 0 },
  recent_tasks: [],
  agent_team: [],
};

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(api, "jarvisSession").mockResolvedValue(emptySession);
  vi.spyOn(api, "dashboard").mockResolvedValue(dashboard);
  vi.spyOn(api, "interactionSettings").mockResolvedValue({ mode: "normal", notify_completed: true, notify_approval: true, notify_failed: true, changed_at: "" });
  vi.spyOn(api, "voice").mockResolvedValue({ state: "idle", session_active: false } as never);
  vi.spyOn(api, "computer").mockResolvedValue({ control: "off", current_task: null, active_window: null } as never);
  vi.spyOn(api, "taskControl").mockResolvedValue({ run_id: "run-1", action: null, constraints: [], task_status: "completed" });
  vi.spyOn(api, "taskMemory").mockResolvedValue({ run_id: "run-1", usage: [] });
  vi.spyOn(api, "approvals").mockResolvedValue([]);
  vi.spyOn(api, "evidence").mockResolvedValue([]);
});

function renderJarvis() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><I18nProvider><MemoryRouter><Jarvis /></MemoryRouter></I18nProvider></QueryClientProvider>);
}

it("loads the session from the ?session= query param (three-column recent conversations switch)", async () => {
  const load = vi.spyOn(api, "jarvisSession").mockResolvedValue({ ...emptySession, session_id: "conv-a", messages: [{ role: "assistant", content: "MetaGPT 研究报告要点", status: "completed" }] });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nProvider><MemoryRouter initialEntries={["/?session=conv-a"]}><Jarvis /></MemoryRouter></I18nProvider>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(load).toHaveBeenCalledWith("conv-a"));
  expect(await screen.findByText("MetaGPT 研究报告要点")).toBeInTheDocument();
});

it("shows a conversation-first empty state and sends a direct conversation", async () => {
  vi.spyOn(api, "jarvisTurn").mockResolvedValue({
    session: { ...emptySession, messages: [{ role: "user", content: "你好" }, { role: "assistant", content: "你好，我是 JARVIS。", status: "completed", run_id: "conv-run" }] },
    result: { status: "completed", summary: "你好，我是 JARVIS。", run_id: "conv-run" },
    run_kind: "conversation",
  });
  renderJarvis();

  expect(await screen.findByText("你好，我是 JARVIS。")) .toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("给 JARVIS 发消息"), { target: { value: "你好" } });
  fireEvent.click(screen.getByLabelText("发送"));

  await waitFor(() => expect(api.jarvisTurn).toHaveBeenCalled());
  expect(screen.queryByLabelText("当前任务")).not.toBeInTheDocument();
});

it("renders a readable summary for structured results saved by older releases", async () => {
  vi.spyOn(api, "jarvisSession").mockResolvedValue({
    ...emptySession,
    messages: [
      { role: "user", content: "你好" },
      { role: "assistant", content: JSON.stringify({ summary: "你好，我是 JARVIS。", decision: "accept" }), status: "completed" },
    ],
  });
  renderJarvis();
  expect(await screen.findByText("你好，我是 JARVIS。")).toBeInTheDocument();
  expect(screen.queryByText(/decision/)).not.toBeInTheDocument();
});

it("restores the latest conversation run instead of an older stopped task", async () => {
  vi.spyOn(api, "jarvisSession").mockResolvedValue({
    ...emptySession,
    messages: [
      { role: "user", content: "第二个详细一点" },
      { role: "assistant", content: "MetaGPT 详情", run_id: "run-latest", task_id: "task-latest", status: "completed" },
    ],
  });
  vi.spyOn(api, "dashboard").mockResolvedValue({
    ...dashboard,
    recent_tasks: [
      { task_id: "task-old", run_id: "run-old", status: "paused", run_kind: "user_task", goal: "旧任务", project_id: "default", model_mode: "real", tokens: 0, cost: 0, tool_calls: 0, started_at: null, duration_s: null },
    ],
  });
  vi.spyOn(api, "task").mockImplementation(async (runId) => ({
    task_id: runId === "run-latest" ? "task-latest" : "task-old",
    run_id: runId,
    current_status: "completed",
    run_kind: "user_task",
    failure_code: null,
    model_mode: "real",
    goal: runId === "run-latest" ? "详细研究 FoundationAgents/MetaGPT" : "旧任务",
    plan: null,
    subtasks: [],
    token_budget: 10000,
    cost_budget: 1,
    budget_usage: {},
    rework_count: 0,
    final_result: "MetaGPT 详情",
  } as TaskDetail));
  vi.spyOn(api, "taskUsage").mockResolvedValue({ total_tokens: 100, by_agent: [], context: { percentage: null } } as unknown as UsageSummary);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(new ReadableStream({ start() {} }), { status: 200 }));
  renderJarvis();
  // 该 goal 会同时出现在任务卡片与右侧 Inspector 的 Overview（三栏架构），允许出现多次
  expect((await screen.findAllByText("详细研究 FoundationAgents/MetaGPT")).length).toBeGreaterThanOrEqual(1);
  expect(screen.queryByText("旧任务")).not.toBeInTheDocument();
});

it("renders real task usage, execution summary and final result in the same thread", async () => {
  const session = { ...emptySession, messages: [{ role: "user" as const, content: "研究 Agent 项目" }, { role: "assistant" as const, content: "已完成研究。", status: "completed", run_id: "run-1", task_id: "task-1" }] };
  vi.spyOn(api, "jarvisSession").mockResolvedValue(session);
  vi.spyOn(api, "dashboard").mockResolvedValue({ ...dashboard, recent_tasks: [{ task_id: "task-1", run_id: "run-1", status: "completed", run_kind: "user_task", goal: "研究 Agent 项目", project_id: "default", model_mode: "real", tokens: 4441, cost: 0.001, tool_calls: 1, started_at: "2026-08-14T00:00:00Z", duration_s: 18 }] });
  const task = { task_id: "task-1", run_id: "run-1", current_status: "completed", run_kind: "user_task", failure_code: null, model_mode: "real", goal: "研究 Agent 项目", plan: { goal: "研究", subtasks: [] }, subtasks: [{ subtask_id: "s1", title: "检索候选项目", role: "researcher", status: "completed", rework_count: 0, dependencies: [], token_budget: 5000, tool_call_budget: 2, evidence_refs: ["e1"] }], token_budget: 10000, cost_budget: 1, budget_usage: { tokens: 4441 }, rework_count: 0, final_result: JSON.stringify({ summary: "### 推荐项目 A。", decision: "accept", execution_summary: { tool_call_count: 1 } }), model_identity: { badge: "REAL", provider: "DeepSeek Official", default_model: "deepseek-v4-flash", role_models: { researcher: "deepseek-v4-flash" } } } satisfies TaskDetail;
  const usage = { has_data: true, requests: 3, total_tokens: 4441, input_tokens: 4000, output_tokens: 441, reasoning_tokens: null, cached_input_tokens: null, cache_write_tokens: null, other_tokens: null, cost_total: 0.001, currency: "USD", cache_hit_rate: null, cache_hit_tokens: null, cache_miss_tokens: null, token_cache_hit_ratio: null, runtime_ms: 18000, average_latency_ms: 6000, usage_source: "REPORTED", last_compression: null, context: { current_tokens: 140000, limit: 1000000, percentage: .14, status: "AMPLE", compression_threshold: .8, compression_threshold_tokens: 800000, until_compression: 660000, source: "REPORTED", role: "researcher", model: "deepseek-v4-flash" }, by_agent: [{ name: "researcher", requests: 3, tokens: 4441, latency_ms: 18000, cost: .001, cost_available: true }], by_model: [], by_provider: [], by_task: [], timeline: [] } satisfies UsageSummary;
  vi.spyOn(api, "task").mockResolvedValue(task);
  vi.spyOn(api, "taskUsage").mockResolvedValue(usage);
  vi.spyOn(api, "approvals").mockResolvedValue([]);
  vi.spyOn(api, "evidence").mockResolvedValue([{ evidence_id: "e1", title: "GitHub" }]);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(new ReadableStream({ start() {} }), { status: 200 }));

  renderJarvis();
  expect(await screen.findByLabelText("当前任务")).toBeInTheDocument();
  expect(screen.getAllByText("4.4K tokens").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("推荐项目 A。")).toBeInTheDocument();
  expect(screen.queryByText(/execution_summary/)).not.toBeInTheDocument();
  expect(await screen.findByText("依据 1 个来源")).toBeInTheDocument();
  expect(screen.getByText("研究员")).toBeInTheDocument();
});

it("steers a running task without creating a duplicate task", async () => {
  const session = { ...emptySession, messages: [{ role: "user" as const, content: "研究 Agent 项目" }, { role: "assistant" as const, content: "正在研究", run_id: "run-1", task_id: "task-1" }] };
  vi.spyOn(api, "jarvisSession").mockResolvedValue(session);
  vi.spyOn(api, "dashboard").mockResolvedValue({ ...dashboard, metrics: { ...dashboard.metrics, active_tasks: 1 }, recent_tasks: [{ task_id: "task-1", run_id: "run-1", status: "running", run_kind: "user_task", goal: "研究 Agent 项目", project_id: "default", model_mode: "real", tokens: 120, cost: 0, tool_calls: 0, started_at: "2026-08-14T00:00:00Z", duration_s: null }] });
  vi.spyOn(api, "task").mockResolvedValue({ task_id: "task-1", run_id: "run-1", current_status: "executing", run_kind: "user_task", failure_code: null, model_mode: "real", goal: "研究 Agent 项目", plan: { goal: "研究", subtasks: [] }, subtasks: [], token_budget: 10000, cost_budget: 1, budget_usage: { tokens: 120 }, rework_count: 0, final_result: null } as TaskDetail);
  vi.spyOn(api, "taskUsage").mockResolvedValue({ has_data: false, total_tokens: 120, by_agent: [], context: { percentage: .01 } } as unknown as UsageSummary);
  vi.spyOn(api, "taskControl").mockResolvedValue({ run_id: "run-1", action: null, constraints: [], task_status: "executing" });
  const steer = vi.spyOn(api, "steerTask").mockResolvedValue({ run_id: "run-1", steering_kind: "CHANGE_SCOPE", session: { ...session, messages: [...session.messages, { role: "user", content: "只看 GitHub" }, { role: "assistant", content: "已加入要求" }] } });
  const turn = vi.spyOn(api, "jarvisTurn");
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(new ReadableStream({ start() {} }), { status: 200 }));
  renderJarvis();
  await screen.findByLabelText("当前任务");
  fireEvent.change(screen.getByLabelText("给 JARVIS 发消息"), { target: { value: "只看 GitHub" } });
  fireEvent.click(screen.getByLabelText("发送"));
  await waitFor(() => expect(steer).toHaveBeenCalledWith("run-1", "只看 GitHub", "jarvis-desktop"));
  expect(turn).not.toHaveBeenCalled();
  expect(screen.getAllByLabelText("当前任务")).toHaveLength(1);
});

it("shows security approval inline", async () => {
  vi.spyOn(api, "jarvisSession").mockResolvedValue({ ...emptySession, messages: [{ role: "user", content: "删除文件", run_id: "run-1" }] });
  vi.spyOn(api, "dashboard").mockResolvedValue({ ...dashboard, recent_tasks: [{ task_id: "task-1", run_id: "run-1", status: "paused", run_kind: "user_task", goal: "删除文件", project_id: "default", model_mode: "real", tokens: 10, cost: 0, tool_calls: 0, started_at: null, duration_s: null }] });
  vi.spyOn(api, "task").mockResolvedValue({ task_id: "task-1", run_id: "run-1", current_status: "paused", run_kind: "user_task", failure_code: null, model_mode: "real", goal: "删除文件", plan: null, subtasks: [], token_budget: 10000, cost_budget: 1, budget_usage: {}, rework_count: 0, final_result: null, pending_approval_id: "ap-1" } as TaskDetail);
  vi.spyOn(api, "taskUsage").mockResolvedValue({ total_tokens: 10, by_agent: [], context: { percentage: null } } as unknown as UsageSummary);
  vi.spyOn(api, "taskControl").mockResolvedValue({ run_id: "run-1", action: null, constraints: [], task_status: "paused", pending_approval_id: "ap-1" });
  vi.spyOn(api, "approvals").mockResolvedValue([{ approval_id: "ap-1", task_id: "task-1", status: "pending", action_type: "delete", tool_name: "workspace_delete", risk_level: "destructive", summary: "这一步会删除 3 个临时文件。", target_paths: ["temp"], requested_at: "now", expires_at: null }]);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(new ReadableStream({ start() {} }), { status: 200 }));
  renderJarvis();
  expect(await screen.findByText("需要你的确认")).toBeInTheDocument();
  expect(screen.getByText("这一步会删除 3 个临时文件。")).toBeInTheDocument();
  expect(screen.getByText("允许")).toBeInTheDocument();
  expect(screen.getByText("拒绝")).toBeInTheDocument();
});

it("turns a runtime failure into recovery choices with optional technical detail", async () => {
  vi.spyOn(api, "jarvisSession").mockResolvedValue({ ...emptySession, messages: [{ role: "user", content: "研究项目", run_id: "run-1" }] });
  vi.spyOn(api, "dashboard").mockResolvedValue({ ...dashboard, recent_tasks: [{ task_id: "task-1", run_id: "run-1", status: "failed", run_kind: "user_task", goal: "研究项目", project_id: "default", model_mode: "real", tokens: 10, cost: 0, tool_calls: 0, started_at: null, duration_s: null }] });
  vi.spyOn(api, "task").mockResolvedValue({ task_id: "task-1", run_id: "run-1", current_status: "failed", run_kind: "user_task", failure_code: "provider_timeout", model_mode: "real", goal: "研究项目", plan: null, subtasks: [], token_budget: 10000, cost_budget: 1, budget_usage: {}, rework_count: 0, final_result: null } as TaskDetail);
  vi.spyOn(api, "taskUsage").mockResolvedValue({ total_tokens: 10, by_agent: [], context: { percentage: null } } as unknown as UsageSummary);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(new ReadableStream({ start() {} }), { status: 200 }));
  renderJarvis();
  expect(await screen.findByText("遇到一个问题")).toBeInTheDocument();
  expect(screen.getByText("模型服务暂时没有返回完整结果。")).toBeInTheDocument();
  expect(screen.getByText("重试")).toBeInTheDocument();
  expect(screen.getByText("查看技术详情")).toBeInTheDocument();
});
