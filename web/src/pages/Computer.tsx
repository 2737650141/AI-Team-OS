import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  Monitor,
  Pause,
  Play,
  RefreshCw,
  Shield,
  Square,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import type { ComputerStatus } from "../api/types";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";

type Capability = "observe_only" | "low_risk_control" | "ask_every_action";

export function Computer() {
  const { lang } = useI18n();
  const qc = useQueryClient();
  const [capability, setCapability] = useState<Capability>("observe_only");
  const [goal, setGoal] = useState("");
  const [screen, setScreen] = useState<string | null>(null);
  const [error, setError] = useState("");
  const zh = lang === "zh";
  const text = useMemo(() => ({
    title: zh ? "电脑控制" : "Computer Control",
    subtitle: zh ? "Windows 桌面感知、受控操作与实时可视化" : "Windows observation, governed actions and live visibility",
    screen: zh ? "当前屏幕" : "Current Screen",
    session: zh ? "控制会话" : "Control Session",
    active: zh ? "当前应用" : "Active App",
    plan: zh ? "操作计划" : "Action Plan",
    approval: zh ? "待批准动作" : "Pending Approval",
    history: zh ? "Windows 动作" : "Windows Actions",
    safety: zh ? "安全状态" : "Safety Status",
    start: zh ? "开始控制" : "Start Control",
    pause: zh ? "暂停" : "Pause",
    resume: zh ? "继续" : "Resume",
    stop: zh ? "立即停止控制" : "STOP CONTROL",
    refresh: zh ? "刷新屏幕" : "Refresh screen",
    planTask: zh ? "生成操作计划" : "Create action plan",
    runPlan: zh ? "执行已显示的计划" : "Run displayed plan",
    approve: zh ? "批准" : "Approve",
    reject: zh ? "拒绝" : "Reject",
    off: zh ? "电脑控制当前关闭。AI Team OS 无权观察或操作桌面。" : "Computer Control is off. AI Team OS cannot observe or act on the desktop.",
    ephemeral: zh ? "截图仅在内存中显示，不会写入任务、记忆或审计原始数据。" : "Screens are displayed from memory only and are not written to tasks, memory or raw audit data.",
    screenAccess: zh ? "屏幕访问" : "Screen Access",
    control: zh ? "控制" : "Control",
    status: zh ? "状态" : "Status",
    capability: zh ? "会话能力" : "Capability",
    actions: zh ? "动作" : "Actions",
    expires: zh ? "到期" : "Expires",
  }), [zh]);

  const status = useQuery({
    queryKey: ["computer"],
    queryFn: api.computer,
    refetchInterval: (query) => query.state.data?.control === "on" ? 1500 : false,
  });
  const refresh = (data?: ComputerStatus) => {
    if (data) qc.setQueryData(["computer"], data);
    else void qc.invalidateQueries({ queryKey: ["computer"] });
  };
  const mutation = useMutation({
    mutationFn: async (action: string) => {
      setError("");
      if (action === "start") return api.startComputer(capability);
      if (action === "pause") return api.pauseComputer();
      if (action === "resume") return api.resumeComputer();
      return api.stopComputer();
    },
    onSuccess: (data) => { refresh(data); if (data.control === "off") setScreen(null); },
    onError: (e: Error) => setError(e.message),
  });
  const planMutation = useMutation({
    mutationFn: api.planComputerTask,
    onSuccess: () => refresh(),
    onError: (e: Error) => setError(e.message),
  });
  const runMutation = useMutation({
    mutationFn: api.runComputerTask,
    onSuccess: () => refresh(),
    onError: (e: Error) => { setError(e.message); refresh(); },
  });
  const approvalMutation = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "approve" | "reject" }) =>
      decision === "approve" ? api.approveComputerAction(id) : api.rejectComputerAction(id),
    onSuccess: () => refresh(),
    onError: (e: Error) => { setError(e.message); refresh(); },
  });
  const data = status.data;
  const controlOn = data?.control === "on";
  const controlPaused = data?.control === "paused";

  async function capture() {
    try {
      setError("");
      const frame = data?.active_window?.window_id
        ? await api.computerWindowScreen(data.active_window.window_id)
        : await api.computerScreen();
      setScreen(`data:${frame.mime_type};base64,${frame.image_base64}`);
      refresh();
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <div className="page computer-page">
      <header className="page-header computer-header">
        <div><h1>{text.title}</h1><p>{text.subtitle}</p></div>
        <div className={`jarvis-state ${data?.jarvis_status ?? "idle"}`}>
          <span /> JARVIS STATUS · {displayLabel(data?.jarvis_status, lang)}
        </div>
        {(controlOn || controlPaused) && (
          <button className="danger stop-control" onClick={() => mutation.mutate("stop")}>
            <Square size={15} /> {text.stop}
          </button>
        )}
      </header>
      {error && <div className="alert error"><AlertTriangle size={16} /> {error}</div>}
      <section className="computer-privacy-strip">
        <span><Eye size={15} /> {text.screenAccess} <strong className={data?.screen_access ? "ok" : "muted"}>{data?.screen_access ? "ON" : "OFF"}</strong></span>
        <span><Monitor size={15} /> {text.control} <strong>{(data?.control ?? "off").toUpperCase()}</strong></span>
        <span><Shield size={15} /> {text.ephemeral}</span>
      </section>

      {!data?.session || data.control === "off" ? (
        <section className="card computer-start-card">
          <Monitor size={34} /><h2>{text.session}</h2><p>{text.off}</p>
          <label>{zh ? "会话能力" : "Session capability"}
            <select value={capability} onChange={(e) => setCapability(e.target.value as Capability)}>
              <option value="observe_only">{zh ? "仅观察" : "Observe only"}</option>
              <option value="low_risk_control">{zh ? "低风险控制" : "Low-risk control"}</option>
              <option value="ask_every_action">{zh ? "每个动作前询问" : "Ask before every action"}</option>
            </select>
          </label>
          <button onClick={() => mutation.mutate("start")} disabled={mutation.isPending}><Play size={15} /> {text.start}</button>
        </section>
      ) : (
        <div className="computer-grid">
          <section className="card live-screen-panel">
            <div className="section-head"><h2>{text.screen}</h2><button onClick={capture}><RefreshCw size={14} /> {text.refresh}</button></div>
            <div className="live-screen">
              {screen ? <img src={screen} alt={text.screen} /> : <div><Eye size={32} /><p>{zh ? "手动刷新以获取一次临时截图" : "Refresh manually for one ephemeral screen frame"}</p></div>}
            </div>
            <p className="privacy-note"><Shield size={13} /> {text.ephemeral}</p>
          </section>

          <aside className="computer-side">
            <section className="card session-card">
              <div className="section-head"><h2>{text.session}</h2><span className={`status-dot ${data.control}`} /> </div>
              <dl><dt>{text.status}</dt><dd>{data.session.status === "paused" ? text.pause : displayLabel(data.session.status, lang)}</dd><dt>{text.capability}</dt><dd>{displayLabel(data.session.capability, lang)}</dd><dt>{text.actions}</dt><dd>{data.session.action_count}</dd><dt>{text.expires}</dt><dd>{new Date(data.session.expires_at).toLocaleTimeString()}</dd></dl>
              <div className="button-row">
                {controlOn ? <button onClick={() => mutation.mutate("pause")}><Pause size={14} /> {text.pause}</button> : <button onClick={() => mutation.mutate("resume")}><Play size={14} /> {text.resume}</button>}
                <button className="danger" onClick={() => mutation.mutate("stop")}><Square size={14} /> {text.stop}</button>
              </div>
            </section>
            <section className="card active-app-card"><h2>{text.active}</h2><strong>{data.active_window?.title || "—"}</strong><small>{data.windows.length} {zh ? "个可见窗口" : "visible windows"}</small></section>
          </aside>

          <section className="card action-task-panel">
            <h2>{zh ? "Windows 任务" : "Windows Task"}</h2>
            <textarea value={goal} onChange={(e) => setGoal(e.target.value)} placeholder={zh ? "例如：打开记事本，在里面输入测试文字，不要保存文件。" : "Example: Open Notepad, type test text, and do not save."} />
            <button onClick={() => planMutation.mutate(goal)} disabled={!goal.trim() || planMutation.isPending}><Play size={14} /> {text.planTask}</button>
            {data.current_task && <div className="real-identity"><span className="mode-badge real">REAL</span><strong>{data.current_task.provider}</strong><span>{data.current_task.model}</span><span className={`task-status ${data.current_task.status}`}>{displayLabel(data.current_task.status, lang)}</span></div>}
          </section>

          <section className="card action-plan-panel">
            <div className="section-head"><h2>{text.plan}</h2>{data.current_task?.status === "planned" && <button onClick={() => runMutation.mutate(data.current_task!.task_id)}><Play size={14} /> {text.runPlan}</button>}</div>
            {data.current_task?.memory_preference_applied && <p className="memory-applied"><CheckCircle2 size={14} /> {zh ? "已应用偏好：控制电脑前先显示操作计划" : "Preference applied: show the plan before controlling the computer"}</p>}
            {data.current_task?.planner_recovered && <p className="memory-applied"><AlertTriangle size={14} /> {zh ? "真实 Planner 的结构修复已耗尽；已使用服务器受限安全计划。" : "Real Planner schema repair was exhausted; a server-bounded safe plan was used."}</p>}
            {!!data.current_task?.replan_count && <p className="memory-applied"><RefreshCw size={14} /> {zh ? `Supervisor 已安全重规划 ${data.current_task.replan_count} 次。` : `Supervisor safely replanned ${data.current_task.replan_count} time(s).`}</p>}
            <ol className="action-plan-list">{data.current_task?.action_plan.map((step) => <li key={step.step_id} className={step.status}><span>{step.status === "completed" ? <CheckCircle2 size={15} /> : step.status === "failed" ? <XCircle size={15} /> : <span className="step-number">{step.step_id.replace("step-", "")}</span>}</span><div><strong>{displayLabel(step.tool, lang)}</strong><p>{step.rationale}</p><small>{step.expected_state} · {displayLabel(step.risk, lang)}</small></div></li>)}</ol>
            {data.current_task?.result && <p className="task-result">{data.current_task.result}</p>}
          </section>

          <section className="card approval-panel"><h2>{text.approval}</h2>{data.pending_actions.length ? data.pending_actions.map((item) => <article key={item.approval_id}><AlertTriangle size={17} /><div><strong>{item.summary}</strong><pre>{JSON.stringify(item.arguments_display, null, 2)}</pre></div><div className="button-row"><button className="danger" onClick={() => approvalMutation.mutate({ id: item.approval_id, decision: "reject" })}>{text.reject}</button><button onClick={() => approvalMutation.mutate({ id: item.approval_id, decision: "approve" })}>{text.approve}</button></div></article>) : <p className="muted">{zh ? "没有待批准动作" : "No pending actions"}</p>}</section>

          <section className="card action-history-panel"><h2>{text.history}</h2><div className="action-feed">{data.recent_actions.slice().reverse().map((item) => <article key={item.action_id}><time>{new Date(item.timestamp).toLocaleTimeString()}</time><span className={`action-icon ${item.status}`}>{item.status === "completed" ? <CheckCircle2 size={14} /> : <XCircle size={14} />}</span><div><strong>{item.summary}</strong><small>{item.verification || item.error_code} {item.retry_count ? `· retry ${item.retry_count}` : ""}</small></div></article>)}</div></section>

          <section className="card safety-panel"><h2>{text.safety}</h2><div className="safety-grid">{Object.entries(data.safety_status).filter(([, value]) => typeof value !== "object").map(([key, value]) => <span key={key}><Shield size={13} /><small>{displayLabel(key, lang)}</small><strong>{displayLabel(String(value), lang)}</strong></span>)}</div></section>
        </div>
      )}
    </div>
  );
}
