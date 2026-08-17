import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Check,
  ChevronDown,
  Circle,
  LoaderCircle,
  Paperclip,
  PanelRightOpen,
  Pause,
  Play,
  Send,
  Sparkles,
  Square,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { JarvisMessage, TaskDetail, TaskSummary } from "../api/types";
import { ActivityFeed } from "../components/ActivityFeed";
import { ApprovalCard } from "../components/ApprovalCard";
import { RightInspector } from "../components/RightInspector";
import { StatusBadge } from "../components/StatusBadge";
import { useEvents } from "../hooks/useEvents";
import { useConversationScroll } from "../hooks/useConversationScroll";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";

const SESSION_KEY = "ai-team-os.jarvis-session";

function sessionId() {
  // The desktop voice adapter uses this same stable working-context session.
  const value = "jarvis-desktop";
  window.localStorage.setItem(SESSION_KEY, value);
  return value;
}

export function Jarvis() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const requestedSession = params.get("session");
  const requestedProject = params.get("project");
  const [inspectorOpen, setInspectorOpen] = useState(true);
  // 024-B：会话/项目来自 URL query，随路由切换实时生效（三栏 Recent conversations 切换）
  const [session, setSession] = useState(() =>
    requestedSession && requestedSession !== "jarvis-desktop" ? requestedSession : sessionId(),
  );
  const [projectContext, setProjectContext] = useState<string | undefined>(requestedProject ?? undefined);
  useEffect(() => {
    setSession(requestedSession && requestedSession !== "jarvis-desktop" ? requestedSession : sessionId());
    setProjectContext(requestedProject ?? undefined);
  }, [requestedSession, requestedProject]);
  const [input, setInput] = useState("");
  const [optimistic, setOptimistic] = useState<JarvisMessage[]>([]);
  const [focusedRun, setFocusedRun] = useState<string | undefined>(() => {
    const value = window.localStorage.getItem("ai-team-os.jarvis-focus-run") ?? undefined;
    window.localStorage.removeItem("ai-team-os.jarvis-focus-run");
    return value;
  });
  const [focusedKind, setFocusedKind] = useState<"user_task" | "conversation">();
  const [expanded, setExpanded] = useState(false);
  const [undoMessage, setUndoMessage] = useState("");
  const [startingTurn, setStartingTurn] = useState(false);

  const conversation = useQuery({
    queryKey: ["jarvis-session", session],
    queryFn: () => api.jarvisSession(session),
  });
  const conversationMessages = conversation.data?.messages ?? [];
  const latestMessage = conversationMessages.at(-1);
  const messageVersion = latestMessage
    ? latestMessage.run_id ?? `${latestMessage.role}:${latestMessage.content}`
    : "";
  // 024-C ConversationScrollController：滚动状态按会话隔离并持久化
  const { containerRef, onScroll, unreadCount, jumpToLatest } = useConversationScroll(
    session,
    conversation.data,
    conversationMessages.length,
    messageVersion,
  );
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    refetchInterval: (query) => hasActiveTask(query.state.data?.recent_tasks) ? 1200 : 2500,
  });

  const latestSessionRun = [...(conversation.data?.messages ?? [])]
    .reverse()
    .find((message) => message.run_id)?.run_id ?? undefined;
  const activeSummary = dashboard.data?.recent_tasks.find((task) =>
    ["created", "running", "paused"].includes(task.status),
  );
  const recentSummary = dashboard.data?.recent_tasks[0];
  const runId = focusedRun
    ?? (startingTurn ? activeSummary?.run_id : latestSessionRun ?? activeSummary?.run_id)
    ?? recentSummary?.run_id;
  const task = useQuery({
    queryKey: ["jarvis-task", runId],
    queryFn: () => api.task(runId!),
    enabled: !!runId,
    refetchInterval: (query) => isTerminal((query.state.data as TaskDetail | undefined)?.current_status) ? false : 1800,
  });
  const isUserTask = focusedKind
    ? focusedKind === "user_task"
    : task.data?.run_kind !== "conversation";
  const usage = useQuery({
    queryKey: ["jarvis-task-usage", runId],
    queryFn: () => api.taskUsage(runId!),
    enabled: !!runId && isUserTask,
    refetchInterval: isTerminal(task.data?.current_status) ? false : 3500,
  });
  const approvals = useQuery({
    queryKey: ["jarvis-approvals", runId],
    queryFn: () => api.approvals(runId!),
    enabled: !!runId && isUserTask,
    refetchInterval: task.data?.current_status === "paused" ? 2000 : false,
  });
  const evidence = useQuery({
    queryKey: ["jarvis-evidence", runId],
    queryFn: () => api.evidence(runId!),
    enabled: !!runId && isUserTask && !!task.data,
  });
  const interaction = useQuery({ queryKey: ["interaction-settings"], queryFn: api.interactionSettings });
  const voice = useQuery({ queryKey: ["jarvis-voice-status"], queryFn: api.voice, refetchInterval: 3000 });
  const computer = useQuery({ queryKey: ["jarvis-computer-status"], queryFn: api.computer, refetchInterval: 3000 });
  const taskMemory = useQuery({
    queryKey: ["jarvis-task-memory", runId],
    queryFn: () => api.taskMemory(runId!),
    enabled: !!runId && isUserTask && !!task.data,
  });
  const control = useQuery({
    queryKey: ["jarvis-task-control", runId],
    queryFn: () => api.taskControl(runId!),
    enabled: !!runId && isUserTask && !!task.data,
    refetchInterval: isTerminal(task.data?.current_status) ? false : 1800,
  });
  const { events, connected } = useEvents(runId, !!runId && isUserTask);
  const patchApproval = approvals.data?.find((item) => item.action_type === "patch" && item.status === "approved");
  const taskIsTerminal = isTerminal(task.data?.current_status) || (task.data?.current_status === "paused" && control.data?.action === "stop");
  const undo = useMutation({
    mutationFn: () => api.rollback(runId!, patchApproval!.approval_id),
    onSuccess: () => setUndoMessage(zh ? "已撤销这次工作区更改。" : "The workspace changes were undone."),
    onError: (error) => setUndoMessage(error instanceof Error ? error.message : String(error)),
  });

  const submit = useMutation({
    mutationFn: (user_input: string) => api.jarvisTurn(session, { user_input, model_mode: "real", ...(projectContext ? { project_id: projectContext } : {}) }),
    onMutate: (user_input) => {
      setStartingTurn(true);
      setOptimistic([{ role: "user", content: user_input }]);
      setFocusedRun(undefined);
      setFocusedKind(undefined);
    },
    onSuccess: (response) => {
      setStartingTurn(false);
      qc.setQueryData(["jarvis-session", session], response.session);
      setFocusedRun(response.result.run_id);
      setFocusedKind(response.run_kind);
      setOptimistic([]);
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => {
      setStartingTurn(false);
      setOptimistic((messages) => [
        ...messages,
        {
          role: "assistant",
          content: zh
            ? `遇到一个问题：${humanizeError(error)}。当前会话已保留，你可以重试。`
            : `I hit a problem: ${humanizeError(error)}. Your conversation is safe and you can retry.`,
          status: "error",
        },
      ]);
    },
  });

  const steering = useMutation({
    mutationFn: (instruction: string) => api.steerTask(runId!, instruction, session),
    onMutate: (instruction) => {
      setOptimistic([{ role: "user", content: instruction }]);
    },
    onSuccess: (response) => {
      if (response.session) qc.setQueryData(["jarvis-session", session], response.session);
      setFocusedRun(response.run_id);
      setFocusedKind("user_task");
      setOptimistic([]);
      void qc.invalidateQueries({ queryKey: ["jarvis-task", response.run_id] });
      void qc.invalidateQueries({ queryKey: ["jarvis-task-control", response.run_id] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => {
      setOptimistic((messages) => [
        ...messages,
        {
          role: "assistant",
          content: zh
            ? `调整任务时遇到问题：${humanizeError(error)}。当前任务仍然保留。`
            : `I could not adjust the task: ${humanizeError(error)}. The current task is still intact.`,
          status: "error",
        },
      ]);
    },
  });

  const messages = [...(conversation.data?.messages ?? []), ...optimistic];
  const pendingApproval = approvals.data?.find((item) => item.status === "pending");
  const status = computer.data?.control === "on" && computer.data.current_task && !isTerminal(computer.data.current_task.status)
    ? { label: ["正在操作电脑", "Using computer"], tone: "active" }
    : jarvisStatus(task.data, events, submit.isPending, pendingApproval != null, control.data?.action);
  const placeholder = pendingApproval
    ? zh ? "可以继续补充要求，或处理上方确认……" : "Add a requirement, or respond to the confirmation above…"
    : task.data && !taskIsTerminal
      ? zh ? "继续这个任务，或者告诉我怎么调整……" : "Continue this task or tell me what to adjust…"
      : task.data?.current_status === "completed"
        ? zh ? "继续追问，或者开始下一件事……" : "Ask a follow-up or start something new…"
        : zh ? "给 JARVIS 一个任务……" : "Give JARVIS a task…";

  const send = (event: FormEvent) => {
    event.preventDefault();
    const value = input.trim();
    const canSteer = !!runId && isUserTask && !!task.data && !taskIsTerminal;
    if (!value || steering.isPending || (submit.isPending && !canSteer)) return;
    setInput("");
    if (canSteer) steering.mutate(value);
    else submit.mutate(value);
  };

  return (
    <div className="jarvis-workspace">
      <div className={`jarvis-columns ${inspectorOpen ? "" : "inspector-closed"}`}>
        <section className="jarvis-center">
          <header className="jarvis-topbar">
            <div className="session-header-primary">
              <div className="jarvis-identity">
                <span className={`jarvis-orb ${status.tone}`} aria-hidden="true" />
                <div><strong>JARVIS</strong><span role="status" aria-live="polite">{status.label[zh ? 0 : 1]}</span></div>
              </div>
              <RuntimeModel task={task.data} zh={zh} />
              {!inspectorOpen && <button className="inspector-open" onClick={() => setInspectorOpen(true)} aria-label={zh ? "打开检查器" : "Open Inspector"}><PanelRightOpen size={15} /></button>}
            </div>
            <RuntimeMetrics usage={usage.data} zh={zh} />
          </header>

          <main className="jarvis-scroll" ref={containerRef} onScroll={onScroll} aria-label={zh ? "JARVIS 对话" : "JARVIS conversation"}>
            {unreadCount > 0 && (
              <button className="jarvis-unread-jump" onClick={jumpToLatest}>
                ↓ {zh ? `${unreadCount} 条新消息` : `${unreadCount} new messages`}
              </button>
            )}
            {messages.length === 0 && !conversation.isLoading ? (
              <EmptyState zh={zh} onExample={(value) => setInput(value)} />
            ) : (
              <div className="jarvis-thread">
                {messages.map((message, index) => {
                  const messageId = stableMessageId(messages, index);
                  return <Message key={messageId} message={message} messageId={messageId} />;
                })}
              </div>
            )}

            {isUserTask && task.data && (
              <TaskCard
                task={task.data}
                summary={activeSummary ?? recentSummary}
                events={events}
                connected={connected}
                usage={usage.data}
                evidenceCount={evidence.data?.length ?? 0}
                expanded={expanded}
                setExpanded={setExpanded}
                zh={zh}
                controlAction={control.data?.action}
                controlBusy={steering.isPending}
                onControl={(instruction) => steering.mutate(instruction)}
              />
            )}

            {pendingApproval && <div className="jarvis-inline-approval"><ApprovalCard approval={pendingApproval} onDecision={() => { void approvals.refetch(); void task.refetch(); }} /></div>}

            {taskMemory.data && taskMemory.data.usage.length > 0 && <MemoryExplanation usage={taskMemory.data.usage} zh={zh} onForget={async (memoryId) => { await api.forgetMemory(memoryId); await taskMemory.refetch(); }} />}

            {isUserTask && task.data?.current_status === "failed" && (
              <HumanizedFailure task={task.data} events={events} zh={zh} onRetry={() => { setFocusedRun(undefined); setFocusedKind(undefined); submit.mutate(task.data!.goal); }} />
            )}

            {isUserTask && task.data?.final_result && (
              <section className="jarvis-final" aria-label={zh ? "最终结果" : "Final result"}>
                <div className="message-avatar"><Sparkles size={16} /></div>
                <div className="message-body">
                  <span className="message-name">JARVIS</span>
                  <div className="final-summary"><strong>{zh ? "完成" : "Completed"}</strong><p>{humanizeFinalResult(task.data.final_result)}</p></div>
                  {evidence.data && evidence.data.length > 0 && (
                    <details className="evidence-summary"><summary>{zh ? `依据 ${evidence.data.length} 个来源` : `Based on ${evidence.data.length} sources`}</summary>{evidence.data.slice(0, 12).map((item) => <div key={item.evidence_id}>{item.title || item.source_type || item.tool || (zh ? "已验证来源" : "Verified source")}</div>)}</details>
                  )}
                  {patchApproval && <div className="undo-row"><button disabled={undo.isPending || !!undoMessage} onClick={() => undo.mutate()}>{zh ? "撤销这次更改" : "Undo these changes"}</button><span>{undoMessage}</span></div>}
                  {!patchApproval && task.data.goal.startsWith("sandbox_") && <p className="muted undo-unavailable">{zh ? "此操作没有可用的自动撤销快照。" : "No automatic rollback snapshot is available for this action."}</p>}
                </div>
              </section>
            )}
          </main>

          {(voice.data?.state !== "idle" || computer.data?.control === "on") && <div className="jarvis-capability-strip">
            {voice.data?.state !== "idle" && <span><span className="live-dot" />{voiceLabel(voice.data?.state, zh)}</span>}
            {computer.data?.control === "on" && <span>{zh ? "正在操作电脑" : "Using computer"}{computer.data.active_window?.title ? ` · ${computer.data.active_window.title}` : ""}{computer.data.current_task?.action_plan?.[computer.data.current_task.current_step]?.tool ? ` · ${computer.data.current_task.action_plan[computer.data.current_task.current_step].tool}` : ""}</span>}
          </div>}

          <form className="jarvis-composer" onSubmit={send}>
            <button type="button" className="composer-icon" disabled title={zh ? "文件与图片支持即将接入" : "File and image support is not connected yet"} aria-label={zh ? "添加附件（尚未接入）" : "Add attachment (not connected)"}><Paperclip size={18} /></button>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={placeholder}
              aria-label={zh ? "给 JARVIS 发消息" : "Message JARVIS"}
              rows={1}
            />
            <button
              className="composer-send"
              disabled={!input.trim() || steering.isPending || (submit.isPending && !(runId && isUserTask && task.data && !taskIsTerminal))}
              aria-label={zh ? "发送" : "Send"}
            >
              {steering.isPending || (submit.isPending && !(runId && isUserTask && task.data && !taskIsTerminal)) ? <LoaderCircle className="spin" size={18} /> : <Send size={18} />}
            </button>
            {interaction.data?.mode === "minimal_interruption" && <span className="interaction-mode-indicator">{zh ? "少打扰" : "Minimal"}</span>}
          </form>
        </section>

        {inspectorOpen && <RightInspector runId={runId} task={task.data} usage={usage.data} events={events} connected={connected} onClose={() => setInspectorOpen(false)} />}
      </div>
    </div>
  );
}

function MemoryExplanation({ usage, zh, onForget }: { usage: import("../api/types").MemoryUsage[]; zh: boolean; onForget: (memoryId: string) => Promise<void> }) {
  const [message, setMessage] = useState("");
  const item = usage[0];
  return <aside className="jarvis-memory-note"><div><strong>{zh ? "已按你的习惯" : "Applied your confirmed preference"}</strong><p>{item.value}</p><small>{zh ? "为什么这样" : "Why"}: {item.reason_selected}</small></div><button onClick={() => void onForget(item.memory_id).then(() => setMessage(zh ? "已忘记" : "Forgotten"))}>{zh ? "不要记这个" : "Forget this"}</button>{message && <span>{message}</span>}</aside>;
}

function EmptyState({ zh, onExample }: { zh: boolean; onExample: (value: string) => void }) {
  const examples = zh ? ["分析一个项目", "帮我处理文件", "查看电脑当前状态"] : ["Analyze a project", "Help me organize files", "Check the current computer status"];
  return <section className="jarvis-empty"><div className="empty-orb"><Bot size={30} /></div><h1>{zh ? "你好，我是 JARVIS。" : "Hello, I’m JARVIS."}</h1><p>{zh ? "你可以直接告诉我想完成什么。" : "Tell me what you want to accomplish."}</p><div className="jarvis-examples">{examples.map((item) => <button key={item} onClick={() => onExample(item)}>{item}</button>)}</div></section>;
}

function stableMessageId(messages: JarvisMessage[], index: number) {
  const message = messages[index];
  const pairedRunId = message.role === "user" ? messages[index + 1]?.run_id : undefined;
  const runId = message.run_id ?? pairedRunId;
  return runId ? `${runId}-${message.role}` : `message-${index}`;
}

function Message({ message, messageId }: { message: JarvisMessage; messageId: string }) {
  if (!message.content) return null;
  const content = message.role === "assistant" ? humanizeFinalResult(message.content) : message.content;
  return <article className={`jarvis-message ${message.role}`} data-message-id={messageId}>{message.role === "assistant" && <div className="message-avatar" aria-hidden="true"><Sparkles size={15} /></div>}<div className="message-body"><span className="message-name">{message.role === "assistant" ? "JARVIS" : "You"}</span><p>{content}</p></div></article>;
}

function TaskCard({ task, summary, events, connected, usage, evidenceCount, expanded, setExpanded, zh, controlAction, controlBusy, onControl }: {
  task: TaskDetail;
  summary?: TaskSummary;
  events: import("../api/types").RuntimeEvent[];
  connected: boolean;
  usage?: import("../api/types").UsageSummary;
  evidenceCount: number;
  expanded: boolean;
  setExpanded: (value: boolean) => void;
  zh: boolean;
  controlAction?: "pause" | "stop" | null;
  controlBusy: boolean;
  onControl: (instruction: string) => void;
}) {
  const activeSubtask = task.subtasks.find((item) => ["running", "executed", "rejected"].includes(item.status));
  const stages = useMemo(() => taskStages(task, zh), [task, zh]);
  const latest = events.at(-1)?.summary;
  return <section className="jarvis-task-card" aria-label={zh ? "当前任务" : "Current task"}>
    <div className="task-card-head"><div><span className="eyebrow">{zh ? "当前工作" : "Current work"}</span><h2>{task.goal}</h2></div><StatusBadge status={controlAction === "stop" ? "stopped" : task.current_status} /></div>
    <div className="execution-summary">
      {stages.map((stage) => <div key={stage.label} className={`execution-step ${stage.state}`}>{stage.state === "done" ? <Check size={15} /> : stage.state === "active" ? <LoaderCircle className="spin" size={15} /> : <Circle size={13} />}<span>{stage.label}</span></div>)}
    </div>
    {(latest || activeSubtask) && <p className="current-activity"><span className="live-dot" />{latest || activeSubtask?.title}</p>}
    {usage?.by_agent && usage.by_agent.length > 0 && <div className="task-agents">{usage.by_agent.map((agent) => <div key={agent.name}><strong>{displayLabel(agent.name, zh ? "zh" : "en")}</strong><span>{agent.requests} {zh ? "次请求" : "requests"} · {formatTokens(agent.tokens)} tokens</span></div>)}</div>}
    <div className="task-card-meta"><span>{task.model_identity?.badge ?? (task.model_mode === "real" ? "REAL" : "DEMO")} · {task.model_identity?.provider ?? task.model_mode}</span><span>{formatTokens(usage?.total_tokens)} tokens</span>{summary?.duration_s != null && <span>{humanDuration(summary.duration_s, zh)}</span>}{evidenceCount > 0 && <span>{zh ? `${evidenceCount} 个依据` : `${evidenceCount} sources`}</span>}<span className={connected ? "sse-connected" : "muted"}>{connected ? (zh ? "实时" : "Live") : (zh ? "同步中" : "Syncing")}</span></div>
    {!isTerminal(task.current_status) && controlAction === "stop" && task.current_status === "paused" ? <p className="task-stopped">{zh ? "任务已停止，已完成的工作和证据仍然保留。" : "Task stopped. Completed work and evidence are preserved."}</p> : !isTerminal(task.current_status) && <div className="task-controls">
      {task.current_status === "paused" && !task.pending_approval_id ? <button disabled={controlBusy} onClick={() => onControl(zh ? "继续" : "resume")}><Play size={14} />{zh ? "继续" : "Resume"}</button> : <button disabled={controlBusy || !!controlAction} onClick={() => onControl(zh ? "暂停" : "pause")}><Pause size={14} />{controlAction === "pause" ? (zh ? "正在安全暂停" : "Pausing safely") : (zh ? "暂停" : "Pause")}</button>}
      <button className="stop" disabled={controlBusy || controlAction === "stop"} onClick={() => onControl(zh ? "停止" : "stop")}><Square size={13} />{controlAction === "stop" ? (zh ? "正在安全停止" : "Stopping safely") : (zh ? "停止" : "Stop")}</button>
    </div>}
    <button className="execution-toggle" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>{zh ? "详细过程" : "Detailed activity"}<ChevronDown className={expanded ? "open" : ""} size={16} /></button>
    {expanded && <div className="execution-detail"><ActivityFeed events={events} /></div>}
  </section>;
}

function RuntimeModel({ task, zh }: { task?: TaskDetail; zh: boolean }) {
  const badge = task?.model_identity?.badge ?? (task?.model_mode === "fake" ? "DEMO" : "REAL");
  return <div className="runtime-model" aria-label={zh ? "当前模型" : "Current model"}><b className={`mode-badge ${badge.toLowerCase()}`}>{badge}</b><strong>{task?.model_identity?.default_model || task?.model_identity?.provider || (zh ? "等待任务" : "Ready")}</strong></div>;
}

function RuntimeMetrics({ usage, zh }: { usage?: import("../api/types").UsageSummary; zh: boolean }) {
  const context = usage?.context;
  return <div className="jarvis-runtime-usage" aria-label={zh ? "当前用量" : "Current usage"}>
    <span>Context <strong>{formatContextPercent(context?.percentage, zh)}</strong>{context?.percentage != null && context.percentage >= .7 ? (zh ? " · 即将整理" : " · compaction soon") : ""}</span>
    <span><strong>{formatTokens(usage?.total_tokens)}</strong> tokens</span>
    <span><strong>{usage?.cost_total == null || usage?.by_agent.some((item) => item.cost_available === false) ? (zh ? "费用不可用" : "Cost unavailable") : `$${usage.cost_total.toFixed(4)}`}</strong></span>
  </div>;
}

function formatContextPercent(value: number | null | undefined, _zh: boolean) {
  if (value == null) return "Unavailable";
  if (value > 0 && value < 0.01) return "<1%";
  return `${Math.round(value * 100)}%`;
}

function taskStages(task: TaskDetail, zh: boolean) {
  const done = task.current_status === "completed";
  const result = [
    { label: zh ? "理解任务" : "Understand the task", state: "done" },
    { label: zh ? "制定方案" : "Create a plan", state: task.plan ? "done" : done ? "done" : "active" },
  ];
  task.subtasks.slice(0, 4).forEach((subtask) => result.push({
    label: `${displayLabel(subtask.role, zh ? "zh" : "en")} · ${subtask.title}`,
    state: ["completed", "approved", "passed"].includes(subtask.status) ? "done" : ["running", "executed", "rejected"].includes(subtask.status) ? "active" : "pending",
  }));
  result.push({ label: zh ? "汇总结果" : "Summarize results", state: done ? "done" : "pending" });
  return result as Array<{ label: string; state: "done" | "active" | "pending" }>;
}

function jarvisStatus(task: TaskDetail | undefined, events: import("../api/types").RuntimeEvent[], sending: boolean, waiting: boolean, controlAction?: "pause" | "stop" | null) {
  if (waiting) return { label: ["等待你的确认", "Waiting for you"], tone: "waiting" };
  if (controlAction === "stop" && task?.current_status === "paused") return { label: ["已停止", "Stopped"], tone: "waiting" };
  if (controlAction === "stop") return { label: ["正在安全停止", "Stopping safely"], tone: "waiting" };
  if (controlAction === "pause") return { label: ["正在安全暂停", "Pausing safely"], tone: "waiting" };
  if (sending && !task) return { label: ["正在理解", "Understanding"], tone: "active" };
  const state = task?.current_status ?? "idle";
  if (state === "completed") return { label: ["已完成", "Completed"], tone: "success" };
  if (state === "failed") return { label: ["遇到问题", "Needs attention"], tone: "error" };
  if (state === "paused") return { label: ["已暂停", "Paused"], tone: "waiting" };
  const last = events.at(-1);
  const actor = `${last?.actor_id ?? ""} ${last?.actor_type ?? ""}`.toLowerCase();
  const type = `${last?.event_type ?? ""}`.toLowerCase();
  if (actor.includes("research") || type.includes("research")) return { label: ["正在研究", "Researching"], tone: "active" };
  if (actor.includes("planner") || type.includes("plan")) return { label: ["正在规划", "Planning"], tone: "active" };
  if (type.includes("computer") || type.includes("visual")) return { label: ["正在操作电脑", "Using computer"], tone: "active" };
  if (["created", "running"].includes(state) || sending) return { label: ["正在处理", "Working"], tone: "active" };
  return { label: ["空闲", "Idle"], tone: "idle" };
}

function HumanizedFailure({ task, events, zh, onRetry }: { task: TaskDetail; events: import("../api/types").RuntimeEvent[]; zh: boolean; onRetry: () => void }) {
  const last = events.at(-1);
  return <section className="jarvis-failure" aria-label={zh ? "任务恢复" : "Task recovery"}>
    <div className="failure-title"><strong>{zh ? "遇到一个问题" : "Something went wrong"}</strong><span>{humanFailure(task.failure_code, zh)}</span></div>
    <p>{zh ? "我已保留当前任务状态和已经获得的结果，并停止继续消耗 Token。" : "I kept the task state and existing results, and stopped further token use."}</p>
    <div className="failure-actions"><button onClick={onRetry}>{zh ? "重试" : "Retry"}</button><details><summary>{zh ? "查看技术详情" : "Technical details"}</summary><dl><div><dt>FailureCode</dt><dd>{task.failure_code || "unknown"}</dd></div><div><dt>Last Event</dt><dd>{last?.event_type || "—"}</dd></div><div><dt>Agent</dt><dd>{last?.actor_id || last?.actor_type || "—"}</dd></div></dl></details></div>
  </section>;
}

function humanFailure(code: string | null, zh: boolean) {
  if (!code) return zh ? "执行没有正常完成。" : "The task did not complete normally.";
  if (code.includes("provider") || code.includes("timeout")) return zh ? "模型服务暂时没有返回完整结果。" : "The model service did not return a complete result.";
  if (code.includes("tool")) return zh ? "一个外部工具暂时无法完成这一步。" : "An external tool could not complete this step.";
  if (code.includes("budget")) return zh ? "任务已到达你设置的用量上限。" : "The task reached your usage limit.";
  return zh ? "这一步未通过运行时验收。" : "This step did not pass runtime validation.";
}

function hasActiveTask(tasks?: TaskSummary[]) { return !!tasks?.some((item) => ["created", "running", "paused"].includes(item.status)); }
function isTerminal(status?: string) { return ["completed", "failed", "stopped", "cancelled"].includes(status ?? ""); }
function formatTokens(value?: number | null) { if (value == null) return "—"; return value >= 1000 ? `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}K` : String(value); }
function humanDuration(seconds: number, zh: boolean) { if (seconds < 60) return zh ? `${Math.round(seconds)} 秒` : `${Math.round(seconds)}s`; return zh ? `${Math.round(seconds / 60)} 分钟` : `${Math.round(seconds / 60)}m`; }
function humanizeError(error: unknown) { const text = error instanceof Error ? error.message : String(error); if (/provider|network|fetch/i.test(text)) return "模型服务暂时不可用"; return text.slice(0, 180); }

function humanizeFinalResult(value: string) {
  try {
    const result = JSON.parse(value) as Record<string, unknown>;
    const summary = [result.summary, result.answer, result.content, result.final_result]
      .find((item): item is string => typeof item === "string" && item.trim().length > 0);
    if (summary) return summary.replace(/^#{1,6}\s+/gm, "").trim();
  } catch {
    // Plain-text results are already ready for the conversation surface.
  }
  return value;
}
function voiceLabel(state: string | undefined, zh: boolean) { const labels: Record<string, [string, string]> = { wake_listening: ["等待唤醒", "Waiting for wake word"], listening: ["正在听", "Listening"], transcribing: ["正在识别", "Transcribing"], thinking: ["正在理解语音", "Understanding voice"], speaking: ["正在回答", "Speaking"], paused: ["语音已暂停", "Voice paused"], error: ["语音遇到问题", "Voice error"] }; return (labels[state ?? ""] ?? ["语音交互", "Voice"])[zh ? 0 : 1]; }
