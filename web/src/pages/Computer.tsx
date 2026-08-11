import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Crosshair,
  Eye,
  Layers3,
  MessageSquare,
  Monitor,
  Pause,
  Play,
  RefreshCw,
  Shield,
  Square,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { ComputerStatus, DesktopObservation, VisualGrounding } from "../api/types";
import { useI18n } from "../i18n";
import { displayLabel } from "../i18n/labels";

type Capability = "observe_only" | "low_risk_control" | "ask_every_action";

export function Computer() {
  const { lang } = useI18n();
  const qc = useQueryClient();
  const [capability, setCapability] = useState<Capability>("observe_only");
  const [goal, setGoal] = useState("");
  const [screen, setScreen] = useState<string | null>(null);
  const [observation, setObservation] = useState<DesktopObservation | null>(null);
  const [grounding, setGrounding] = useState<VisualGrounding | null>(null);
  const [target, setTarget] = useState("");
  const [question, setQuestion] = useState("");
  const [screenAnswer, setScreenAnswer] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [overlay, setOverlay] = useState({ controls: true, accessibility: false, grounding: true });
  const [error, setError] = useState("");
  const zh = lang === "zh";
  const text = useMemo(() => ({
    title: "JARVIS Desktop Control",
    subtitle: zh ? "Windows 屏幕视觉理解、融合定位与受控操作" : "Windows screen understanding, fused grounding and governed actions",
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
    autoRefresh: zh ? "自动刷新（最高 1 FPS）" : "Auto refresh (max 1 FPS)",
    visionOverlay: zh ? "视觉叠加" : "Vision Overlay",
    detected: zh ? "识别控件" : "Detected controls",
    accessibility: "Accessibility",
    grounding: zh ? "定位目标" : "Grounding target",
    ask: zh ? "询问当前屏幕" : "Ask about current screen",
    askPlaceholder: zh ? "这个页面现在有什么？" : "What is on this page?",
    locate: zh ? "视觉定位" : "Ground visual target",
    targetPlaceholder: zh ? "例如：右下角那个蓝色确认按钮" : "Example: the blue confirm button at bottom right",
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
    onSuccess: (data) => {
      refresh(data);
      if (data.control === "off") {
        setScreen(null); setObservation(null); setGrounding(null); setAutoRefresh(false);
      }
    },
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
  const groundingMutation = useMutation({
    mutationFn: ({ observationId, description }: { observationId: string; description: string }) =>
      api.groundComputerVision(observationId, description),
    onSuccess: setGrounding,
    onError: (e: Error) => setError(e.message),
  });
  const askMutation = useMutation({
    mutationFn: ({ prompt, observationId }: { prompt: string; observationId?: string }) =>
      api.askComputerScreen(prompt, observationId),
    onSuccess: (answer) => setScreenAnswer(answer.answer),
    onError: (e: Error) => setError(e.message),
  });
  const visualActionMutation = useMutation({
    mutationFn: (groundingId: string) => api.actComputerVision(groundingId, true),
    onSuccess: (result) => {
      setScreenAnswer(result.verification); setGrounding(null);
      void qc.invalidateQueries({ queryKey: ["computer"] });
    },
    onError: (e: Error) => setError(e.message),
  });
  const data = status.data;
  const controlOn = data?.control === "on";
  const controlPaused = data?.control === "paused";

  const capture = useCallback(async () => {
    try {
      setError("");
      const current = await api.observeComputerVision({ scope: "active_window", external: false });
      const frame = await api.computerVisionPreview(current.observation_id);
      setObservation(current);
      setGrounding(null);
      setScreen(`data:${frame.mime_type};base64,${frame.image_base64}`);
      void qc.invalidateQueries({ queryKey: ["computer"] });
    } catch (e) { setError((e as Error).message); }
  }, [qc]);

  useEffect(() => {
    if (!autoRefresh || !controlOn) return;
    const timer = window.setInterval(() => { void capture(); }, 1000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, capture, controlOn]);

  const overlayElements = observation?.visual_elements.filter((item) => {
    if (item.sensitive) return false;
    if (grounding?.selected_element?.visual_element_id === item.visual_element_id) return overlay.grounding;
    if (overlay.accessibility && item.accessibility_element_id) return true;
    return overlay.controls && (item.clickable_estimate || item.editable_estimate);
  }) ?? [];

  function overlayStyle(item: DesktopObservation["visual_elements"][number]) {
    const frame = observation!.capture_bounds;
    return {
      left: `${((item.bounds.left - frame.left) / (frame.right - frame.left)) * 100}%`,
      top: `${((item.bounds.top - frame.top) / (frame.bottom - frame.top)) * 100}%`,
      width: `${((item.bounds.right - item.bounds.left) / (frame.right - frame.left)) * 100}%`,
      height: `${((item.bounds.bottom - item.bounds.top) / (frame.bottom - frame.top)) * 100}%`,
    };
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
        <span><Layers3 size={15} /> Vision <strong>{displayLabel(observation?.vision_mode ?? "accessibility_only", lang)}</strong></span>
        <span>{text.active} <strong>{data?.active_window?.app_name || "—"}</strong></span>
        <span>Model <strong>DeepSeek · {data?.vision_status?.vision_provider?.multimodal_status ?? "NOT_CONFIGURED"}</strong></span>
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
            <div className="section-head"><h2>{text.screen}</h2><div className="button-row"><button onClick={() => void capture()}><RefreshCw size={14} /> {text.refresh}</button><button className={autoRefresh ? "active" : ""} onClick={() => setAutoRefresh((value) => !value)}><Play size={14} /> {autoRefresh ? text.pause : text.autoRefresh}</button></div></div>
            <div className="live-screen visual-screen">
              {screen ? <><img src={screen} alt={text.screen} />{overlayElements.map((item) => <span key={item.visual_element_id} className={`vision-box ${grounding?.selected_element?.visual_element_id === item.visual_element_id ? "target" : ""} ${item.accessibility_element_id ? "access" : "visual"}`} style={overlayStyle(item)} title={`${item.label || item.element_type} · ${Math.round(item.confidence * 100)}%`}><small>{item.label || item.element_type}</small></span>)}</> : <div><Eye size={32} /><p>{zh ? "手动刷新以获取一次临时截图" : "Refresh manually for one ephemeral screen frame"}</p></div>}
            </div>
            <div className="vision-overlay-controls"><strong><Layers3 size={14} /> {text.visionOverlay}</strong><label><input type="checkbox" checked={overlay.controls} onChange={(event) => setOverlay({ ...overlay, controls: event.target.checked })} /> {text.detected}</label><label><input type="checkbox" checked={overlay.accessibility} onChange={(event) => setOverlay({ ...overlay, accessibility: event.target.checked })} /> {text.accessibility}</label><label><input type="checkbox" checked={overlay.grounding} onChange={(event) => setOverlay({ ...overlay, grounding: event.target.checked })} /> {text.grounding}</label></div>
            {observation && <p className="vision-metadata"><span>{displayLabel(observation.vision_mode, lang)}</span><span>{observation.visual_elements.length} {zh ? "个元素" : "elements"}</span><span>{Math.round(observation.confidence * 100)}%</span><span>{zh ? "预览到期" : "Preview expires"} {new Date(observation.capture_expires_at).toLocaleTimeString()}</span></p>}
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

          <section className="card screen-intelligence-panel">
            <div className="section-head"><h2><MessageSquare size={17} /> {text.ask}</h2><span className="observe-badge">OBSERVE · 0 ACTION</span></div>
            <div className="screen-query-row"><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={text.askPlaceholder} /><button disabled={!question.trim() || askMutation.isPending} onClick={() => askMutation.mutate({ prompt: question, observationId: observation?.observation_id })}><Eye size={14} /> {text.ask}</button></div>
            {screenAnswer && <p className="screen-answer">{screenAnswer}</p>}
            <hr />
            <div className="section-head"><h2><Crosshair size={17} /> {text.locate}</h2><span className="muted">Ground → Validate → Act → Verify</span></div>
            <div className="screen-query-row"><input value={target} onChange={(event) => setTarget(event.target.value)} placeholder={text.targetPlaceholder} /><button disabled={!target.trim() || !observation || groundingMutation.isPending} onClick={() => observation && groundingMutation.mutate({ observationId: observation.observation_id, description: target })}><Crosshair size={14} /> {text.locate}</button></div>
            {grounding && <div className={`visual-target-preview ${grounding.status}`}><div><span>{zh ? "目标" : "Target"}</span><strong>{grounding.selected_element?.label || grounding.target_description}</strong></div><div><span>{zh ? "置信度" : "Confidence"}</span><strong>{Math.round(grounding.confidence * 100)}% · {grounding.confidence_band.toUpperCase()}</strong></div><div><span>{zh ? "来源" : "Source"}</span><strong>{grounding.accessibility_match ? "Accessibility + Vision" : "Visual coordinate fallback"}</strong></div><p>{grounding.reason_summary_safe}</p>{grounding.status === "needs_clarification" ? <p className="warning">{zh ? "存在多个相似目标，请选择高亮候选。" : grounding.clarification_prompt}</p> : grounding.status === "resolved" && <button className="danger" disabled={visualActionMutation.isPending} onClick={() => visualActionMutation.mutate(grounding.grounding_id)}>{zh ? "确认目标并执行" : "Approve target and act"}</button>}</div>}
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
