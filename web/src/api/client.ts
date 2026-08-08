// API 客户端：/api 前缀经 vite 代理到 FastAPI（010 四十六）
const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch {
      /* 忽略解析失败 */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  dashboard: () => request<import("./types").DashboardData>("/dashboard"),
  tasks: () => request<import("./types").TaskSummary[]>("/tasks"),
  task: (runId: string) => request<import("./types").TaskDetail>(`/tasks/${runId}`),
  trace: (runId: string) => request<Record<string, unknown>>(`/tasks/${runId}/trace`),
  evidence: async (runId: string) => {
    const r = await request<{ evidence: import("./types").EvidenceView[] }>(
      `/tasks/${runId}/evidence`,
    );
    return r.evidence;
  },
  evidenceDetail: (evidenceId: string) =>
    request<import("./types").EvidenceDetail>(`/evidence/${evidenceId}`),
  approvals: (runId: string) =>
    request<import("./types").ApprovalView[]>(`/tasks/${runId}/approvals`),
  pendingApprovalRun: async () => {
    const tasks = await request<import("./types").TaskSummary[]>("/tasks");
    for (const task of tasks.filter((item) => item.status === "paused")) {
      const approvals = await request<import("./types").ApprovalView[]>(
        `/tasks/${task.run_id}/approvals`,
      );
      if (approvals.some((approval) => approval.status === "pending")) return task.run_id;
    }
    return null;
  },
  artifacts: (runId: string) =>
    request<Array<{ artifact_id: string; artifact_type: string; subtask_id?: string }>>(
      `/tasks/${runId}/artifacts`,
    ),
  artifact: (artifactId: string) =>
    request<import("./types").ArtifactDetail>(`/artifacts/${artifactId}`),
  diff: (runId: string) =>
    request<{ diff: string; files?: import("./types").DiffFile[] }>(`/tasks/${runId}/diff`),
  agents: () => request<import("./types").AgentInfo[]>("/agents"),
  tools: async () => {
    const r = await request<{ tools: import("./types").ToolInfo[] }>("/tools");
    return r.tools;
  },
  health: () => request<import("./types").SystemHealth>("/system/health"),
  settingsStatus: () => request<Record<string, unknown>>("/settings/status"),
  connections: () => request<Record<string, import("./types").ConnectionStatus>>("/settings/connections"),
  saveConnection: (provider: string, body: Record<string, unknown>) =>
    request<{ provider: string; configured: boolean }>(`/settings/connections/${provider}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteCredential: (provider: string) =>
    request<{ provider: string; configured: boolean }>(
      `/settings/connections/${provider}/credential`,
      { method: "DELETE" },
    ),
  testConnection: (provider: string) =>
    request<{ status: string; detail: string }>(`/settings/connections/${provider}/test`, {
      method: "POST",
    }),
  discoverModels: (provider: string) =>
    request<import("./types").ModelDiscovery>(`/settings/connections/${provider}/models`),
  createTask: (body: {
    goal: string;
    model_mode: string;
    token_budget?: number;
    cost_budget?: number;
    project_alias?: string | null;
  }) => request<{ run_id: string; task_id: string; status: string }>("/tasks", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  approve: (approvalId: string, reason?: string) =>
    request<{ status: string }>(`/approvals/${approvalId}/approve`, {
      method: "POST",
      body: JSON.stringify(reason ? { reason } : {}),
    }),
  reject: (approvalId: string, reason?: string) =>
    request<{ status: string }>(`/approvals/${approvalId}/reject`, {
      method: "POST",
      body: JSON.stringify(reason ? { reason } : {}),
    }),
};

// SSE：订阅 run 事件（Last-Event-ID 自动恢复）
export function subscribeEvents(
  runId: string,
  onEvent: (ev: import("./types").RuntimeEvent) => void,
  onDone?: () => void,
): () => void {
  let lastId = 0;
  let closed = false;
  const connect = () => {
    if (closed) return;
    const es = new EventSource(`${BASE}/tasks/${runId}/events${lastId ? `?after=${lastId}` : ""}`);
    es.addEventListener("message", (msg) => {
      try {
        const ev = JSON.parse((msg as MessageEvent<string>).data) as import("./types").RuntimeEvent;
        // 只有 completed/failed 才是终态；paused 的状态事件必须继续订阅返工/审批事件。
        const terminalStatus =
          (ev as import("./types").RuntimeEvent & { status?: string }).status ??
          String(ev.payload_safe?.status ?? "");
        if (
          ev.event_type === "task_status_changed" &&
          (terminalStatus === "completed" || terminalStatus === "failed")
        ) {
          es.close();
          closed = true;
          onDone?.();
          return;
        }
        // 容忍/忽略非事件消息：缺 sequence 或 event_type（心跳等）不进 Activity Feed
        if (typeof ev.sequence !== "number" || typeof ev.event_type !== "string") return;
        if (ev.sequence > lastId) lastId = ev.sequence;
        onEvent(ev);
      } catch {
        /* 忽略非 JSON（心跳） */
      }
    });
    es.onerror = () => {
      es.close();
      if (!closed) setTimeout(connect, 1500); // 断线重连
    };
    es.onopen = () => {
      /* 已连接 */
    };
    return es;
  };
  const es = connect();
  return () => {
    closed = true;
    es?.close();
    onDone?.();
  };
}
