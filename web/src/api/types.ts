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
  cost_available?: boolean;
  tool_calls: number;
  started_at: string | null;
  duration_s: number | null;
  permission_mode?: PermissionMode;
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
  permission_mode?: PermissionMode;
}

export interface AgentCard {
  role: string;
  status: string;
  current_task: string | null;
  model: string;
  tokens: number;
  last_action: string | null;
  provider?: string;
  route_source?: string | null;
  model_mode?: string;
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
  current_action?: string | null;
  current_subtask?: string | null;
  latest_completed?: string | null;
  provider?: string;
  model_mode?: string;
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
  permission_mode?: PermissionMode;
  permission_mode_at_start?: PermissionMode;
  permission_mode_current?: PermissionMode;
  goal: string;
  plan: { goal?: string; subtasks?: SubtaskView[] } | null;
  subtasks: SubtaskView[];
  token_budget: number;
  cost_budget: number;
  max_model_calls?: number;
  budget_usage: Record<string, number>;
  cost_available?: boolean;
  rework_count: number;
  final_result: string | null;
  memory_context_count?: number;
  personalization_applied_count?: number;
  personalization_applied?: PersonalizationItem[];
  model_identity?: {
    badge: "REAL" | "DEMO";
    provider: string;
    default_model: string;
    role_models: Record<string, string>;
  };
}

export interface MemoryRecord {
  memory_id: string;
  project_id: string | null;
  memory_type: string;
  subject: string;
  predicate: string;
  value: string;
  confidence: number;
  status: string;
  privacy_level: string;
  source_type: string;
  source_ref: string;
  updated_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  version: number;
  tags: string[];
}

export interface MemoryProposal {
  proposal_id: string;
  project_id: string | null;
  memory_type: string;
  subject: string;
  predicate: string;
  proposed_value: string;
  reason: string;
  source_type: string;
  confidence: number;
  privacy_level: string;
  created_at: string;
  status: string;
}

export interface MemoryUsage {
  memory_id: string;
  memory_version: number;
  role: string;
  reason_selected: string;
  scope: string;
  token_count: number;
  subject: string;
  predicate: string;
  value: string;
  source_type: string;
}

export interface MemorySettings {
  enabled: boolean;
  automatic_low_risk: boolean;
  preference_detection: boolean;
  retention: string;
}

export interface CustomProvider {
  provider_id: string;
  provider_name: string;
  base_url: string;
  models_endpoint: string;
  chat_endpoint: string;
  default_model: string;
  role_models: Record<string, string>;
  discovered_models: Array<{ id: string; owned_by?: string; created?: number }>;
  configured: boolean;
  storage: string;
  health: string;
  model_discovery_status: string;
  invocation_status: string;
  model_count: number;
  last_model_sync_at: string | null;
  last_invoked_at: string | null;
  is_default: boolean;
  local_provider: boolean;
  test_provider: boolean;
  context_window?: number | null;
  context_window_source?: "USER_CONFIGURED" | null;
}

export interface UsageGroup {
  name: string;
  requests: number;
  tokens: number;
  latency_ms: number;
  cost: number;
  cost_available: boolean;
}

export interface UsageSummary {
  has_data: boolean;
  requests: number;
  total_tokens: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
  cached_input_tokens: number | null;
  cache_write_tokens: number | null;
  other_tokens: number | null;
  cost_total: number | null;
  currency: string | null;
  cache_hit_rate: number | null;
  runtime_ms: number | null;
    average_latency_ms: number | null;
    usage_source: "REPORTED" | "ESTIMATED" | "UNAVAILABLE";
    last_compression: {
      before_tokens: number | null;
      after_tokens: number | null;
      freed_tokens: number | null;
      timestamp: string;
    } | null;
  context: {
    current_tokens: number | null;
    limit: number | null;
    percentage: number | null;
    status: "AMPLE" | "MODERATE" | "NEAR_COMPACTION" | "COMPACTION_REQUIRED" | "UNKNOWN";
    compression_threshold: number;
    compression_threshold_tokens: number | null;
    until_compression: number | null;
    source: "REPORTED" | "ESTIMATED" | "UNAVAILABLE";
    role: string | null;
    model: string | null;
  };
  by_agent: UsageGroup[];
  by_model: UsageGroup[];
  by_provider: UsageGroup[];
  by_task: UsageGroup[];
    timeline: Array<{
      timestamp: string;
      agent: string;
      model: string;
      tokens: number | null;
      source: string;
      compression_triggered: boolean;
      compression_tokens_before: number | null;
      compression_tokens_after: number | null;
    }>;
}

export type PermissionMode = "safe" | "standard" | "maximum";

export interface PermissionModeSetting {
  mode: PermissionMode;
  changed_at: string;
  changed_by_user: boolean;
  version: number;
  maximum_confirmed: boolean;
  first_upgrade_notice?: boolean;
}

export interface PermissionAction {
  action_id: string;
  timestamp: string;
  task_id?: string | null;
  action: string;
  target: string;
  risk: string;
  permission_mode: PermissionMode;
  decision: "allow" | "ask" | "block";
  reason: string;
}

export interface TeamProvider {
  provider_id: string;
  provider_name: string;
  configured: boolean;
  storage: string;
  health: string;
  models: string[];
  manual_allowed: boolean;
  local_provider: boolean;
  test_provider: boolean;
}

export interface TeamRoleCard {
  role: string;
  provider_id: string | null;
  provider: string | null;
  model: string | null;
  source: "task" | "project" | "global" | null;
  capability: {
    text?: boolean | null;
    structured_output?: boolean | null;
    tool_calling?: boolean | null;
    vision?: boolean | null;
    streaming?: boolean | null;
  };
  health: string;
  latency_ms: number | null;
  success_rate: number | null;
  cost: number | null;
  cost_label: string;
  fallback: { provider_id: string; model: string } | null;
  token_budget: number | null;
  cost_budget?: number | null;
  warning: string | null;
}

export interface TeamRoutingData {
  roles: TeamRoleCard[];
  providers: TeamProvider[];
  precedence: string[];
  fallback_policy: string;
  reviewer_policy: string;
}

export interface TeamTestResult {
  results: Array<{
    role: string;
    provider_id?: string;
    provider?: string;
    model?: string;
    status: string;
    real_call?: boolean;
    latency_ms?: number | null;
    total_tokens?: number | null;
    cost?: number | null;
  }>;
  ready: number;
  total: number;
  status: string;
  max_calls: number;
  max_output_tokens_per_call: number;
}

export interface VoiceSettings {
  voice_enabled: boolean;
  microphone_enabled: boolean;
  wake_word_enabled: boolean;
  push_to_talk: boolean;
  input_device_id: number | null;
  output_device_id: number | null;
  language: "auto" | "zh" | "en";
  whisper_executable: string;
  whisper_model: string;
  vad_model: string;
  wake_model: string;
  tts_voice: string;
  tts_rate: number;
  max_record_seconds: number;
  max_session_turns: number;
  max_session_tokens: number;
  conversation_mode: "single" | "conversation";
  conversation_timeout_seconds: number;
  allow_external_speech_processing: boolean;
}

export interface AudioDevice {
  id: number;
  name: string;
  input_channels: number;
  output_channels: number;
  default_sample_rate: number;
  is_default_input: boolean;
  is_default_output: boolean;
}

export interface VoiceTurn {
  turn_id: string;
  created_at: string;
  user_text: string;
  assistant_text: string;
  route: string;
  action: string;
  task_id: string | null;
}

export interface VoiceStatus {
  state: "idle" | "wake_listening" | "listening" | "transcribing" | "thinking" | "speaking" | "interrupted" | "paused" | "error";
  mic_state: "MIC OFF" | "MIC LISTENING" | "MIC ACTIVE" | "MIC MUTED" | "MIC ERROR";
  session_active: boolean;
  partial_transcript: string;
  final_transcript: string;
  error_code: string | null;
  error_message: string | null;
  input_device: string | null;
  output_device: string | null;
  asr_status: string;
  wake_status: string;
  tts_status: string;
  raw_audio_persisted: boolean;
  local_command_priority: boolean;
  output_suppression: boolean;
  latency: Record<string, number | null>;
  settings: VoiceSettings;
  turns: VoiceTurn[];
}

export interface PersonalizationItem {
  field: string;
  value: string;
  confidence: number;
  scope: string;
  reason: string;
  source: string;
  source_refs: string[];
  enabled: boolean;
  current_task_override: boolean;
}

export interface PersonalizationProfile {
  user_id: string;
  project_id: string | null;
  task_type: string;
  items: PersonalizationItem[];
  security_invariants: Record<string, boolean>;
  generated_at: string;
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
  content_hash?: string;
  content_length?: number;
  freshness?: string | null;
  snapshot_status?: string;
  snapshot_ref?: string | null;
  subtask_id?: string | null;
  subtask_title?: string | null;
  agent?: string | null;
  claims?: Array<{
    claim_id?: string;
    text?: string;
    confidence?: number;
    subtask_id?: string;
    subtask_title?: string;
    agent?: string;
  }>;
}

export interface EvidenceDetail {
  evidence_id: string;
  snapshot: string;
  snapshot_ref: string;
  size: number;
  content_hash: string;
  truncated_for_display: boolean;
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
  test_provider?: boolean;
}

export interface ModelDiscovery {
  supported: boolean;
  models: string[];
  manual_allowed: boolean;
  status?: string;
}

export interface DiffFile {
  path: string;
  status: "M" | "A" | "D" | string;
}

export interface ComputerWindow {
  window_id: string;
  title: string;
  process_id?: number | null;
  app_name: string;
  bounds: { left: number; top: number; right: number; bottom: number };
  is_active: boolean;
  window_hash: string;
}

export interface ComputerActionStep {
  step_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  rationale: string;
  expected_state: string;
  risk: "observe" | "low" | "medium" | "high" | "forbidden";
  status: string;
}

export interface ComputerTask {
  task_id: string;
  goal: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  model_mode: "real";
  provider: string;
  model: string;
  real_call: boolean;
  planner_recovered: boolean;
  replan_count: number;
  action_plan: ComputerActionStep[];
  current_step: number;
  result: string;
  error_code?: string | null;
  memory_preference_applied: boolean;
  reviewer_verdict?: string | null;
  token_usage: Record<string, number | null>;
}

export interface ComputerStatus {
  session?: {
    session_id: string;
    started_at: string;
    expires_at: string;
    status: string;
    capability: string;
    action_count: number;
    last_action_at?: string | null;
  } | null;
  screen_access: boolean;
  control: "on" | "paused" | "off";
  jarvis_status: string;
  active_window?: ComputerWindow | null;
  windows: ComputerWindow[];
  current_task?: ComputerTask | null;
  pending_actions: Array<{
    approval_id: string;
    task_id: string;
    step_id: string;
    tool: string;
    risk: string;
    summary: string;
    arguments_display: Record<string, unknown>;
    status: string;
  }>;
  recent_actions: Array<{
    action_id: string;
    task_id?: string | null;
    step_id?: string | null;
    timestamp: string;
    tool: string;
    risk: string;
    status: string;
    summary: string;
    verification?: string | null;
    error_code?: string | null;
    retry_count: number;
  }>;
  safety_status: Record<string, unknown>;
  vision_status?: VisionStatus;
}

export interface ComputerScreen {
  captured_at: string;
  screenshot_hash: string;
  bounds: { left: number; top: number; right: number; bottom: number };
  image_base64: string;
  mime_type: string;
  ephemeral: boolean;
}

export interface VisualElement {
  visual_element_id: string;
  label: string;
  element_type: string;
  text: string;
  icon_hint: string;
  bounds: { left: number; top: number; right: number; bottom: number };
  confidence: number;
  source: string;
  accessibility_element_id?: string | null;
  clickable_estimate: boolean;
  editable_estimate: boolean;
  sensitive: boolean;
}

export interface DesktopObservation {
  observation_id: string;
  timestamp: string;
  active_window?: ComputerWindow | null;
  screen_bounds: { left: number; top: number; right: number; bottom: number };
  capture_bounds: { left: number; top: number; right: number; bottom: number };
  visual_elements: VisualElement[];
  privacy_redactions: Array<{
    redaction_id: string;
    bounds: { left: number; top: number; right: number; bottom: number };
    reason: string;
  }>;
  source_modes: string[];
  capture_id: string;
  capture_hash: string;
  capture_expires_at: string;
  confidence: number;
  vision_mode: string;
}

export interface VisualGrounding {
  grounding_id: string;
  observation_id: string;
  capture_id: string;
  target_description: string;
  candidate_elements: Array<{
    visual_element_id: string;
    label: string;
    bounds: { left: number; top: number; right: number; bottom: number };
    score: number;
    source: string;
  }>;
  selected_element?: VisualElement | null;
  selected_bounds?: { left: number; top: number; right: number; bottom: number } | null;
  confidence: number;
  confidence_band: string;
  reason_summary_safe: string;
  accessibility_match: boolean;
  requires_coordinate_fallback: boolean;
  status: string;
  clarification_prompt?: string | null;
}

export interface VisionStatus {
  desktop_visual_layer?: string;
  vision_provider?: {
    provider: string;
    model: string;
    supports_image_input: boolean;
    external_processing: boolean;
    consent_acknowledged: boolean;
    multimodal_status: string;
    text_model: { provider: string; model: string; real: boolean };
  };
  settings?: {
    route_provider?: string | null;
    route_model?: string | null;
    allow_external_processing: boolean;
    consent_acknowledged: boolean;
    auto_refresh: boolean;
    max_refresh_fps: number;
  };
  active_captures?: number;
  recent_observations?: Array<Record<string, unknown>>;
  recent_groundings?: Array<Record<string, unknown>>;
  recent_actions?: Array<Record<string, unknown>>;
}
