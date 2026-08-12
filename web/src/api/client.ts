// API 客户端：/api 前缀经 vite 代理到 FastAPI（010 四十六）
let desktopSession: Promise<{ base_url: string; token: string } | null> | null = null;

async function endpoint(path: string) {
  const tauri = "__TAURI_INTERNALS__" in window;
  if (!tauri) return { url: `/api${path}`, token: "" };
  for (let attempt = 0; attempt < 80; attempt += 1) {
    desktopSession ??= import("@tauri-apps/api/core")
      .then(({ invoke }) => invoke<{ base_url: string; token: string }>("desktop_session"))
      .catch(() => null);
    const session = await desktopSession;
    if (session?.base_url) return { url: `${session.base_url}${path}`, token: session.token };
    desktopSession = null;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Desktop backend did not become ready.");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const target = await endpoint(path);
  const resp = await fetch(target.url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(target.token ? { "X-Desktop-Session": target.token } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || detail);
    } catch {
      /* 忽略解析失败 */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

function queryString(values: Record<string, string | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const api = {
  dashboard: () => request<import("./types").DashboardData>("/dashboard"),
  tasks: () => request<import("./types").TaskSummary[]>("/tasks"),
  task: (runId: string) => request<import("./types").TaskDetail>(`/tasks/${runId}`),
  usage: (days = 30, runId?: string, taskId?: string) =>
    request<import("./types").UsageSummary>(
      `/usage${queryString({ days: String(days), run_id: runId, task_id: taskId })}`,
    ),
  taskUsage: (runId: string) =>
    request<import("./types").UsageSummary>(`/tasks/${runId}/usage`),
  activeContext: () => request<{
    active: boolean;
    run_id?: string;
    context: import("./types").UsageSummary["context"] | null;
  }>("/usage/active-context"),
  usageSettings: () => request<{ retention: "7" | "30" | "90" | "forever" }>("/settings/usage"),
  saveUsageSettings: (retention: "7" | "30" | "90" | "forever") =>
    request<{ retention: string }>("/settings/usage", {
      method: "PUT",
      body: JSON.stringify({ retention }),
    }),
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
  permissionMode: () => request<import("./types").PermissionModeSetting>("/settings/security/permission-mode"),
  savePermissionMode: (mode: import("./types").PermissionMode, confirmed = false) =>
    request<import("./types").PermissionModeSetting>("/settings/security/permission-mode", {
      method: "PUT",
      body: JSON.stringify({ mode, confirmed, user_explicit_action: true }),
    }),
  permissionHistory: () => request<{ actions: import("./types").PermissionAction[] }>("/security/permission-history"),
  explainPermission: (body: Record<string, unknown>) => request<Record<string, unknown>>("/security/policy/explain", { method: "POST", body: JSON.stringify(body) }),
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
  memories: (params = "") =>
    request<{ memories: import("./types").MemoryRecord[]; metrics: Record<string, number | string | boolean> }>(`/memory${params}`),
  memorySearch: (query: string) =>
    request<{ memories: import("./types").MemoryRecord[] }>(`/memory/search?q=${encodeURIComponent(query)}`),
  memoryProposals: () =>
    request<{ proposals: import("./types").MemoryProposal[] }>("/memory/proposals"),
  confirmMemory: (proposalId: string) =>
    request<import("./types").MemoryRecord>(`/memory/proposals/${proposalId}/confirm`, { method: "POST" }),
  rejectMemory: (proposalId: string) =>
    request<import("./types").MemoryProposal>(`/memory/proposals/${proposalId}/reject`, { method: "POST" }),
  editConfirmMemory: (proposalId: string, value: string) =>
    request<import("./types").MemoryRecord>(`/memory/proposals/${proposalId}/edit-confirm`, {
      method: "POST",
      body: JSON.stringify({ value }),
    }),
  forgetMemory: (memoryId: string) =>
    request<import("./types").MemoryRecord>(`/memory/${memoryId}`, { method: "DELETE" }),
  exportMemory: () => request<Record<string, unknown>>("/memory/export", { method: "POST" }),
  memorySettings: () => request<import("./types").MemorySettings>("/settings/memory"),
  saveMemorySettings: (body: import("./types").MemorySettings) =>
    request<import("./types").MemorySettings>("/settings/memory", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  taskMemory: (runId: string) =>
    request<{ run_id: string; usage: import("./types").MemoryUsage[] }>(`/tasks/${runId}/memory`),
  customProviders: () =>
    request<{ providers: import("./types").CustomProvider[] }>("/settings/connections/providers"),
  createCustomProvider: (body: Record<string, unknown>) =>
    request<import("./types").CustomProvider>("/settings/connections/providers", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateCustomProvider: (providerId: string, body: Record<string, unknown>) =>
    request<import("./types").CustomProvider>(`/settings/connections/providers/${providerId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteCustomProvider: (providerId: string) =>
    request<{ deleted: boolean }>(`/settings/connections/providers/${providerId}`, { method: "DELETE" }),
  saveCustomCredential: (providerId: string, apiKey: string, storageMode: string) =>
    request<{ configured: boolean }>(`/settings/connections/providers/${providerId}/credential`, {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey, storage_mode: storageMode }),
    }),
  deleteCustomCredential: (providerId: string) =>
    request<{ configured: boolean }>(`/settings/connections/providers/${providerId}/credential`, { method: "DELETE" }),
  testCustomProvider: (providerId: string) =>
    request<{ status: string }>(`/settings/connections/providers/${providerId}/test`, { method: "POST" }),
  testCustomModel: (providerId: string, model?: string) =>
    request<{ status: string; real_call: boolean; provider: string; model: string; input_tokens: number; output_tokens: number; cached_tokens: number | null; total_tokens: number; usage_available: boolean; latency_ms: number; estimated_cost: number | null; repair_attempts: number }>(`/settings/connections/providers/${providerId}/test-model`, { method: "POST", body: JSON.stringify({ model: model || null }) }),
  discoverCustomModels: (providerId: string, refresh = false) =>
    request<{ status: string; models: Array<{ id: string }>; count: number }>(`/settings/connections/providers/${providerId}/${refresh ? "refresh-models" : "discover-models"}`, { method: "POST" }),
  teamRouting: (projectId?: string) =>
    request<import("./types").TeamRoutingData>(`/settings/ai-team/routing${queryString({ project_id: projectId })}`),
  saveTeamRoute: (role: string, body: Record<string, unknown>) =>
    request<{ route: Record<string, unknown>; card: import("./types").TeamRoleCard }>(`/settings/ai-team/routing/${encodeURIComponent(role)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteTeamRoute: (role: string, scope = "global", projectId?: string) =>
    request<{ deleted: boolean }>(`/settings/ai-team/routing/${encodeURIComponent(role)}${queryString({ scope, project_id: projectId })}`, { method: "DELETE" }),
  testAiTeam: () => request<import("./types").TeamTestResult>("/settings/ai-team/test", { method: "POST" }),
  teamPerformance: () => request<{ profiles: Array<Record<string, unknown>>; automatic_routing: boolean }>("/settings/ai-team/performance"),
  voice: () => request<import("./types").VoiceStatus>("/voice/status"),
  voiceDevices: () => request<{ devices: import("./types").AudioDevice[]; status: string }>("/voice/devices"),
  saveVoiceSettings: (body: import("./types").VoiceSettings) => request<import("./types").VoiceStatus>("/voice/settings", { method: "PUT", body: JSON.stringify(body) }),
  startVoice: () => request<import("./types").VoiceStatus>("/voice/session/start", { method: "POST" }),
  stopVoice: () => request<import("./types").VoiceStatus>("/voice/session/stop", { method: "POST" }),
  pauseVoice: () => request<import("./types").VoiceStatus>("/voice/session/pause", { method: "POST" }),
  resumeVoice: () => request<import("./types").VoiceStatus>("/voice/session/resume", { method: "POST" }),
  startVoicePtt: () => request<import("./types").VoiceStatus>("/voice/ptt/start", { method: "POST" }),
  stopVoicePtt: () => request<import("./types").VoiceStatus>("/voice/ptt/stop", { method: "POST" }),
  speakVoice: (text: string) => request<import("./types").VoiceStatus>("/voice/speak", { method: "POST", body: JSON.stringify({ text }) }),
  personalization: (projectId?: string, taskType = "general", goal = "") =>
    request<{ profile: import("./types").PersonalizationProfile; proposals: import("./types").MemoryProposal[] }>(`/personalization${queryString({ project_id: projectId, task_type: taskType, goal })}`),
  savePersonalizationControl: (body: Record<string, unknown>) =>
    request<import("./types").PersonalizationProfile>("/personalization/control", { method: "PUT", body: JSON.stringify(body) }),
  resetPersonalization: (projectId?: string, field?: string) =>
    request<{ reset: number }>(`/personalization/reset${queryString({ project_id: projectId, field })}`, { method: "DELETE" }),
  decidePersonalization: (proposalId: string, decision: string, projectId?: string) =>
    request<Record<string, unknown>>(`/personalization/proposals/${proposalId}/decision`, { method: "POST", body: JSON.stringify({ decision, project_id: projectId ?? null }) }),
  computer: () => request<import("./types").ComputerStatus>("/computer"),
  startComputer: (capability: "observe_only" | "low_risk_control" | "ask_every_action") =>
    request<import("./types").ComputerStatus>("/computer/session/start", {
      method: "POST",
      body: JSON.stringify({ capability, ttl_minutes: 15 }),
    }),
  pauseComputer: () => request<import("./types").ComputerStatus>("/computer/session/pause", { method: "POST" }),
  resumeComputer: () => request<import("./types").ComputerStatus>("/computer/session/resume", { method: "POST" }),
  stopComputer: () => request<import("./types").ComputerStatus>("/computer/session/stop", { method: "POST" }),
  computerScreen: () => request<import("./types").ComputerScreen>("/computer/screen"),
  computerWindowScreen: (windowId: string) =>
    request<import("./types").ComputerScreen>(
      `/computer/windows/${encodeURIComponent(windowId)}/screen`,
    ),
  computerVision: () => request<import("./types").VisionStatus>("/computer/vision"),
  updateComputerVision: (body: Record<string, unknown>) =>
    request<import("./types").VisionStatus>("/computer/vision/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  observeComputerVision: (body: Record<string, unknown> = {}) =>
    request<import("./types").DesktopObservation>("/computer/vision/observe", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  computerVisionPreview: (observationId: string) =>
    request<{
      capture_id: string;
      image_base64: string;
      mime_type: string;
      expires_at: string;
      bounds: { left: number; top: number; right: number; bottom: number };
    }>(`/computer/vision/observations/${encodeURIComponent(observationId)}/preview`),
  groundComputerVision: (observationId: string, target: string) =>
    request<import("./types").VisualGrounding>("/computer/vision/ground", {
      method: "POST",
      body: JSON.stringify({ observation_id: observationId, target }),
    }),
  askComputerScreen: (question: string, observationId?: string) =>
    request<{
      observation_id: string;
      intent: string;
      answer: string;
      vision_mode: string;
      action_count: number;
    }>("/computer/vision/ask", {
      method: "POST",
      body: JSON.stringify({ question, observation_id: observationId || null }),
    }),
  actComputerVision: (groundingId: string, approved = false) =>
    request<{
      action_id: string;
      status: string;
      attempts: number;
      verification: string;
      change_score: number;
    }>("/computer/vision/actions", {
      method: "POST",
      body: JSON.stringify({ grounding_id: groundingId, approved }),
    }),
  planComputerTask: (goal: string) => request<import("./types").ComputerTask>("/computer/tasks/plan", {
    method: "POST",
    body: JSON.stringify({ goal }),
  }),
  runComputerTask: (taskId: string) => request<import("./types").ComputerTask>(`/computer/tasks/${taskId}/run`, { method: "POST" }),
  approveComputerAction: (approvalId: string) => request<import("./types").ComputerTask>(`/computer/approvals/${approvalId}/approve`, { method: "POST" }),
  rejectComputerAction: (approvalId: string) => request<import("./types").ComputerTask>(`/computer/approvals/${approvalId}/reject`, { method: "POST" }),
  createTask: (body: {
    goal: string;
    model_mode: string;
    token_budget?: number;
    cost_budget?: number;
    max_calls?: number;
    project_id?: string;
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

// Authenticated SSE parser for both browser development and packaged desktop.
export function subscribeEvents(
  runId: string,
  onEvent: (ev: import("./types").RuntimeEvent) => void,
  onDone?: () => void,
): () => void {
  let lastId = 0;
  let closed = false;
  let abort: AbortController | null = null;

  const connect = async () => {
    if (closed) return;
    const suffix = lastId ? `?after=${lastId}` : "";
    const target = await endpoint(`/tasks/${runId}/events${suffix}`);
    abort = new AbortController();
    try {
      const response = await fetch(target.url, {
        headers: target.token ? { "X-Desktop-Session": target.token } : {},
        signal: abort.signal,
      });
      if (!response.ok || !response.body) throw new Error(`event stream ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!closed) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";
        for (const frame of frames) {
          const data = frame.split("\n").find((line) => line.startsWith("data:"))?.slice(5).trim();
          if (!data) continue;
          try {
            const ev = JSON.parse(data) as import("./types").RuntimeEvent;
            const status = String(ev.payload_safe?.status ?? "");
            if (ev.event_type === "task_status_changed" && ["completed", "failed"].includes(status)) {
              closed = true;
              onDone?.();
              return;
            }
            if (typeof ev.sequence !== "number" || typeof ev.event_type !== "string") continue;
            lastId = Math.max(lastId, ev.sequence);
            onEvent(ev);
          } catch {
            // Keep-alive and malformed frames do not belong in the activity feed.
          }
        }
      }
    } catch {
      // Retry unless the caller explicitly closed the subscription.
    }
    if (!closed) setTimeout(() => void connect(), 1500);
  };

  void connect();
  return () => {
    closed = true;
    abort?.abort();
    onDone?.();
  };
}
