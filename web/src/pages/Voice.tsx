import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic, Pause, Play, Settings, Square, Volume2 } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { VoiceStatus } from "../api/types";
import { useI18n } from "../i18n";

export function Voice() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["voice-status"], queryFn: api.voice, refetchInterval: 800 });
  const [message, setMessage] = useState("");
  const startPromise = useRef<Promise<VoiceStatus> | null>(null);
  const apply = (data: VoiceStatus) => qc.setQueryData(["voice-status"], data);
  const session = useMutation({
    mutationFn: (action: "start" | "stop" | "pause" | "resume") => action === "start" ? api.startVoice() : action === "stop" ? api.stopVoice() : action === "pause" ? api.pauseVoice() : api.resumeVoice(),
    onSuccess: apply,
    onError: (error: Error) => setMessage(error.message),
  });
  const beginPtt = () => {
    if (!status.data?.settings.voice_enabled || !status.data.settings.microphone_enabled) return;
    startPromise.current = api.startVoicePtt().then((data) => { apply(data); return data; });
  };
  const endPtt = async () => {
    try {
      await startPromise.current;
      apply(await api.stopVoicePtt());
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { startPromise.current = null; }
  };
  const data = status.data;
  const disabled = !data?.settings.voice_enabled || !data.settings.microphone_enabled;
  const lastReply = [...(data?.turns ?? [])].reverse().find((turn) => turn.assistant_text)?.assistant_text;

  return (
    <div className="page voice-page">
      <div className="page-heading"><div><span className="eyebrow">JARVIS · Local Voice Console</span><h1>{zh ? "语音交互" : "Voice Interaction"}</h1><p className="muted">{zh ? "按住说话，松开后才会提交最终转写。屏幕上的中间文本永远不会触发操作。" : "Hold to speak. Only the final transcript is submitted after release; partial text never triggers actions."}</p></div><Link className="btn" to="/settings"><Settings size={15} /> {zh ? "语音设置" : "Voice settings"}</Link></div>
      <section className={`card jarvis-voice-stage state-${data?.state ?? "idle"}`}>
        <div className="voice-state-row"><span className={`mic-badge ${data?.mic_state === "MIC LISTENING" || data?.mic_state === "MIC ACTIVE" ? "on" : data?.mic_state === "MIC ERROR" ? "error" : ""}`}><Mic size={14} /> {data?.mic_state ?? "MIC OFF"}</span><strong>{stateLabel(data?.state, zh)}</strong><span>{data?.input_device ?? (zh ? "未选择输入设备" : "No input device")}</span></div>
        <button className="jarvis-orb" aria-label={zh ? "按住说话" : "Hold to speak"} disabled={disabled} onPointerDown={beginPtt} onPointerUp={endPtt} onPointerCancel={endPtt}><span /><Mic size={34} /></button>
        <h2>{data?.state === "listening" ? (zh ? "正在聆听…" : "Listening…") : disabled ? (zh ? "请先在设置中开启语音与麦克风" : "Enable voice and microphone in Settings") : (zh ? "按住说话" : "Hold to speak")}</h2>
        <p className="voice-live-text">{data?.partial_transcript || data?.final_transcript || (zh ? "转写内容会显示在这里" : "Transcript appears here")}</p>
        <div className="voice-controls">{!data?.session_active ? <button className="btn btn-primary" disabled={!data?.settings.voice_enabled || session.isPending} onClick={() => session.mutate("start")}><Play size={15} /> {zh ? "启动 JARVIS" : "Start JARVIS"}</button> : <><button className="btn" onClick={() => session.mutate(data.state === "paused" ? "resume" : "pause")}>{data.state === "paused" ? <Play size={15} /> : <Pause size={15} />} {data.state === "paused" ? (zh ? "继续" : "Resume") : (zh ? "暂停" : "Pause")}</button><button className="btn btn-danger" onClick={() => session.mutate("stop")}><Square size={15} /> STOP</button></>}</div>
        {data?.error_message && <div className="voice-error" role="alert"><strong>{data.error_code}</strong><span>{data.error_message}</span></div>}
        {message && <p className="msg error">{message}</p>}
      </section>
      <div className="voice-content-grid"><section className="card"><div className="section-head"><h2>{zh ? "最近对话" : "Recent conversation"}</h2>{lastReply && <button className="icon-button" title={zh ? "朗读最近回复" : "Read latest reply"} onClick={() => api.speakVoice(lastReply).then(apply)}><Volume2 size={16} /></button>}</div>{data?.turns.length ? <div className="voice-turns">{data.turns.map((turn) => <article key={turn.turn_id}><div><strong>{zh ? "你" : "You"}</strong><p>{turn.user_text}</p></div><div><strong>JARVIS · {turn.route}</strong><p>{turn.assistant_text}</p>{turn.task_id && <Link to={`/tasks/${turn.task_id}`}>{zh ? "查看任务" : "Open task"}</Link>}</div></article>)}</div> : <p className="muted">{zh ? "还没有语音对话。" : "No voice turns yet."}</p>}</section><section className="card voice-safety-card"><h2>{zh ? "实时安全状态" : "Live safety status"}</h2><dl className="detail-list"><div><dt>{zh ? "原始音频" : "Raw audio"}</dt><dd>{data?.raw_audio_persisted ? "PERSISTED" : "EPHEMERAL"}</dd></div><div><dt>{zh ? "本地停止优先" : "Local stop priority"}</dt><dd>{data?.local_command_priority ? "ON" : "OFF"}</dd></div><div><dt>{zh ? "扬声器抑制" : "Output suppression"}</dt><dd>{data?.output_suppression ? "ON" : "OFF"}</dd></div><div><dt>ASR</dt><dd>{data?.asr_status ?? "—"}</dd></div><div><dt>Wake</dt><dd>{data?.wake_status ?? "—"}</dd></div><div><dt>TTS</dt><dd>{data?.tts_status ?? "—"}</dd></div>{Object.entries(data?.latency ?? {}).filter(([, value]) => value != null).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{Math.round(value ?? 0)} ms</dd></div>)}</dl><p className="privacy-note">🔒 {zh ? "语音只能拒绝审批，不能批准中高风险操作。" : "Voice may reject approvals but cannot approve medium/high-risk actions."}</p></section></div>
    </div>
  );
}

function stateLabel(state: VoiceStatus["state"] | undefined, zh: boolean) {
  const labels: Record<string, [string, string]> = { idle: ["待命", "Idle"], wake_listening: ["等待唤醒", "Wake listening"], listening: ["聆听", "Listening"], transcribing: ["转写", "Transcribing"], thinking: ["思考", "Thinking"], speaking: ["播报", "Speaking"], interrupted: ["已打断", "Interrupted"], paused: ["已暂停", "Paused"], error: ["安全停止", "Safe error"] };
  return labels[state ?? "idle"]?.[zh ? 0 : 1] ?? state;
}
