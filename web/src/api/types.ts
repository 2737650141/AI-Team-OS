// API 类型（与后端 FastAPI 响应对应；不含任何 Secret 字段）
export interface TaskSummary {
  task_id: string;
  run_id: string;
  status: string;
  goal: string;
  project_id: string;
  model_mode: string;
  tokens: number;
  cost: number;
  tool_calls: number;
  started_at: string | null;
  duration_s: number | null;
}

export interface SystemHealth {
  backend: string;
  langgraph: string;
  sqlite: string;
  event_store: string;
  model_provider: string;
  github: string;
  mcp: string;
  sandbox: string;
  network_isolation: string;
}

export interface DashboardData {
  system: SystemHealth;
  metrics: {
    active_tasks: number;
    completed_tasks: number;
    failed_tasks: number;
    pending_approvals: number;
    evidence_count: number;
    tool_calls: number;
    tokens: number;
    cost: number;
    event_count: number;
  };
  recent_tasks: TaskSummary[];
  agent_team: AgentCard[];
}

export interface AgentCard {
  role: string;
  status: string;
  current_task: string | null;
  model: string;
  tokens: number;
  last_action: string | null;
}

export interface AgentInfo {
  agent_id: string;
  role: string;
  display_name: string;
  model: string;
  enabled: boolean;
  token_limit: number;
  max_tool_calls: number;
  allowed_tools: string[];
  status?: string;
  current_task?: string | null;
  last_action?: string | null;
}

export interface ToolInfo {
  name: string;
  description: string;
  risk_level?: string;
  read_only?: boolean;
  requires_approval?: boolean;
  status?: string;
}

export interface RuntimeEvent {
  event_id: string;
  task_id: string;
  run_id: string;
  timestamp: string;
  sequence: number;
  event_type: string;
  actor_type: string | null;
  actor_id: string | null;
  summary: string;
  payload_safe: Record<string, unknown>;
}

export interface SubtaskView {
  subtask_id: string;
  title: string;
  role: string;
  status: string;
  rework_count: number;
  dependencies: string[];
  token_budget: number;
  tool_call_budget: number;
  evidence_refs: string[];
}

export interface TaskDetail {
  task_id: string;
  run_id: string;
  current_status: string;
  failure_code: string | null;
  model_mode: string;
  goal: string;
  plan: { goal?: string; subtasks?: SubtaskView[] } | null;
  subtasks: SubtaskView[];
  token_budget: number;
  cost_budget: number;
  budget_usage: Record<string, number>;
  rework_count: number;
  final_result: string | null;
}

export interface ApprovalView {
  approval_id: string;
  task_id: string;
  status: string;
  action_type: string;
  tool_name: string;
  risk_level: string;
  summary: string;
  target_paths: string[];
  requested_at: string;
  expires_at: string | null;
  decision_reason?: string | null;
}

export interface EvidenceView {
  evidence_id: string;
  tool?: string;
  source_uri?: string | null;
  summary?: string;
  ts?: string;
  truncated?: boolean;
  source?: string;
  source_type?: string;
  title?: string;
  retrieved_at?: string;
  reliability?: string;
  hash?: string;
  claims?: string[];
}

export interface ArtifactDetail {
  artifact: {
    artifact_id: string;
    artifact_type: string;
    content_hash: string;
    created_at: string;
  };
  content: string;
}

export interface ConnectionStatus {
  provider: string;
  configured: boolean;
  base_url: string;
  models: Record<string, string>;
  storage: string;
  health: string;
  local_provider?: boolean;
}
