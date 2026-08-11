import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { VoiceSettings } from "../api/types";
import { useI18n } from "../i18n";

export function VoiceSettingsPanel() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["voice-status"], queryFn: api.voice });
  const devices = useQuery({ queryKey: ["voice-devices"], queryFn: api.voiceDevices });
  const [draft, setDraft] = useState<VoiceSettings | null>(null);
  const [message, setMessage] = useState("");
  useEffect(() => { if (status.data?.settings) setDraft(status.data.settings); }, [status.data?.settings]);
  const save = useMutation({
    mutationFn: (settings: VoiceSettings) => api.saveVoiceSettings(settings),
    onSuccess: (data) => {
      qc.setQueryData(["voice-status"], data);
      setDraft(data.settings);
      setMessage(zh ? "语音设置已保存。" : "Voice settings saved.");
    },
    onError: (error: Error) => setMessage(error.message),
  });
  const inputs = devices.data?.devices.filter((item) => item.input_channels > 0) ?? [];
  const outputs = devices.data?.devices.filter((item) => item.output_channels > 0) ?? [];
  if (!draft) return <section className="card voice-settings-panel"><p className="muted">{zh ? "正在读取语音运行时…" : "Loading voice runtime…"}</p></section>;
  const set = <K extends keyof VoiceSettings>(key: K, value: VoiceSettings[K]) => setDraft((current) => current ? { ...current, [key]: value } : current);

  return (
    <section className="card voice-settings-panel">
      <div className="section-heading">
        <div><span className="eyebrow">Local-first · Privacy controlled</span><h2>{zh ? "JARVIS 语音" : "JARVIS Voice"}</h2><p className="muted">{zh ? "语音和麦克风默认关闭。原始音频仅在内存与转写所需的临时文件中短暂存在，处理后立即清除。" : "Voice and microphone are off by default. Raw audio exists only briefly in memory and the transcription scratch file, then is deleted."}</p></div>
        <span className={`mode-badge ${draft.voice_enabled ? "real" : "fake"}`}>{draft.voice_enabled ? "VOICE ON" : "VOICE OFF"}</span>
      </div>
      <div className="voice-toggle-grid">
        <label className="switch-card"><input type="checkbox" checked={draft.voice_enabled} onChange={(event) => set("voice_enabled", event.target.checked)} /><span><strong>{zh ? "启用语音交互" : "Enable voice interaction"}</strong><small>{zh ? "关闭时不监听、不转写、不播报" : "No listening, transcription, or speech while off"}</small></span></label>
        <label className="switch-card"><input type="checkbox" checked={draft.microphone_enabled} disabled={!draft.voice_enabled} onChange={(event) => { set("microphone_enabled", event.target.checked); if (!event.target.checked) set("wake_word_enabled", false); }} /><span><strong>{zh ? "允许麦克风" : "Allow microphone"}</strong><small>{zh ? "独立权限；可随时关闭" : "Independent permission; can be revoked anytime"}</small></span></label>
        <label className="switch-card"><input type="checkbox" checked={draft.wake_word_enabled} disabled={!draft.voice_enabled || !draft.microphone_enabled} onChange={(event) => set("wake_word_enabled", event.target.checked)} /><span><strong>{zh ? "唤醒词（实验性）" : "Wake word (experimental)"}</strong><small>{zh ? "默认关闭；检测到扬声器输出时抑制唤醒" : "Off by default; suppressed during speaker output"}</small></span></label>
        <label className="switch-card"><input type="checkbox" checked={draft.allow_external_speech_processing} onChange={(event) => set("allow_external_speech_processing", event.target.checked)} /><span><strong>{zh ? "允许外部语音处理" : "Allow external speech processing"}</strong><small>{zh ? "当前版本仍使用本地 ASR；此开关不会自动上传音频" : "This version still uses local ASR; enabling this does not upload audio automatically"}</small></span></label>
      </div>
      <div className="voice-device-grid">
        <label className="field">{zh ? "输入设备" : "Input device"}<select value={draft.input_device_id ?? ""} onChange={(event) => set("input_device_id", event.target.value ? Number(event.target.value) : null)}><option value="">{zh ? "系统默认" : "System default"}</option>{inputs.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field">{zh ? "输出设备" : "Output device"}<select value={draft.output_device_id ?? ""} onChange={(event) => set("output_device_id", event.target.value ? Number(event.target.value) : null)}><option value="">{zh ? "系统默认" : "System default"}</option>{outputs.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field">{zh ? "识别语言" : "Recognition language"}<select value={draft.language} onChange={(event) => set("language", event.target.value as VoiceSettings["language"])}><option value="auto">Auto</option><option value="zh">中文</option><option value="en">English</option></select></label>
        <label className="field">{zh ? "会话最大轮数" : "Maximum session turns"}<input type="number" min="2" max="50" value={draft.max_session_turns} onChange={(event) => set("max_session_turns", Number(event.target.value))} /></label>
        <label className="field">{zh ? "对话模式" : "Conversation mode"}<select value={draft.conversation_mode} onChange={(event) => set("conversation_mode", event.target.value as VoiceSettings["conversation_mode"])}><option value="single">{zh ? "单次命令" : "Single command"}</option><option value="conversation">{zh ? "连续对话" : "Conversation"}</option></select></label>
        <label className="field">{zh ? "短期上下文 Token 上限" : "Working-context token limit"}<input type="number" min="256" max="20000" value={draft.max_session_tokens} onChange={(event) => set("max_session_tokens", Number(event.target.value))} /></label>
      </div>
      <details className="voice-advanced"><summary>{zh ? "本地模型与高级设置" : "Local models & advanced settings"}</summary><div className="voice-device-grid"><label className="field">whisper.cpp executable<input value={draft.whisper_executable} onChange={(event) => set("whisper_executable", event.target.value)} placeholder="whisper-cli.exe" /></label><label className="field">Whisper model<input value={draft.whisper_model} onChange={(event) => set("whisper_model", event.target.value)} placeholder="ggml-model.bin" /></label><label className="field">Silero VAD model<input value={draft.vad_model} onChange={(event) => set("vad_model", event.target.value)} placeholder="silero_vad.onnx" /></label><label className="field">openWakeWord model<input value={draft.wake_model} onChange={(event) => set("wake_model", event.target.value)} placeholder="hey_jarvis.onnx" /></label><label className="field">SAPI voice<input value={draft.tts_voice} onChange={(event) => set("tts_voice", event.target.value)} placeholder={zh ? "留空使用系统默认" : "Empty uses system default"} /></label></div></details>
      <div className="voice-privacy-strip"><span>🔒 {zh ? "原始音频：不持久化" : "Raw audio: never persisted"}</span><span>🛑 {zh ? "停止/取消/暂停：本地优先" : "Stop/cancel/pause: local priority"}</span><span>🛡 {zh ? "语音不能批准中高风险操作" : "Voice cannot approve medium/high-risk actions"}</span></div>
      <div className="provider-actions"><button className="btn btn-primary" disabled={save.isPending} onClick={() => save.mutate(draft)}>{zh ? "保存语音设置" : "Save voice settings"}</button><span className="muted">ASR {status.data?.asr_status ?? "—"} · Wake {status.data?.wake_status ?? "—"} · TTS {status.data?.tts_status ?? "—"}</span></div>
      {message && <p className="msg" role="status">{message}</p>}
    </section>
  );
}
