import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Rocket, ShieldCheck, Zap } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import type { PermissionMode } from "../api/types";
import { useI18n } from "../i18n";

const MODES = [
  { mode: "safe", icon: ShieldCheck, zh: "安全模式", en: "Safe", descZh: "写入、执行和多数电脑操作都会要求确认。", descEn: "Writes, execution, and most computer actions ask for confirmation.", fitZh: "陌生任务、重要数据、第一次使用", fitEn: "New tasks, important data, first use" },
  { mode: "standard", icon: Zap, zh: "标准模式", en: "Standard", descZh: "普通任务自动执行，只有敏感、外部影响或高风险操作才询问。", descEn: "Normal work runs automatically; sensitive or important external effects ask.", fitZh: "日常使用、代码开发、Research、电脑助理", fitEn: "Daily work, coding, research, desktop assistance" },
  { mode: "maximum", icon: Rocket, zh: "最高权限模式", en: "Maximum", descZh: "自主完成绝大多数任务，不为普通操作反复请求审批。", descEn: "Completes nearly all normal task operations without repeated approvals.", fitZh: "完全信任当前任务环境，希望 JARVIS 跑完整流程", fitEn: "Trusted environments and fully autonomous workflows" },
] as const;

export function PermissionSettingsPanel() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const setting = useQuery({ queryKey: ["permission-mode"], queryFn: api.permissionMode });
  const history = useQuery({ queryKey: ["permission-history"], queryFn: api.permissionHistory });
  const [confirmMaximum, setConfirmMaximum] = useState(false);
  const [message, setMessage] = useState("");
  const save = useMutation({
    mutationFn: ({ mode, confirmed }: { mode: PermissionMode; confirmed?: boolean }) => api.savePermissionMode(mode, confirmed),
    onSuccess: () => {
      setConfirmMaximum(false);
      setMessage(zh ? "权限模式已保存，并立即应用于后续动作。" : "Permission mode saved and applied to subsequent actions.");
      qc.invalidateQueries({ queryKey: ["permission-mode"] });
      qc.invalidateQueries({ queryKey: ["permission-history"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => setMessage(error.message),
  });
  const choose = (mode: PermissionMode) => {
    if (mode === "maximum" && !setting.data?.maximum_confirmed) setConfirmMaximum(true);
    else save.mutate({ mode });
  };

  return <section id="security-permissions" className="card permission-settings-panel">
    <div className="section-heading"><div><span className="eyebrow">Security & Permissions</span><h2>{zh ? "安全与权限" : "Security & Permissions"}</h2><p className="muted">{zh ? "设置一次，重启、新任务和后续操作都会继续使用，直到你主动修改。" : "Choose once. The setting persists across restarts and new tasks until you change it."}</p></div><span className={`permission-badge ${setting.data?.mode ?? "standard"}`}>{zh ? `权限：${setting.data?.mode === "maximum" ? "最高" : setting.data?.mode === "safe" ? "安全" : "标准"}` : `Permissions: ${setting.data?.mode ?? "standard"}`}</span></div>
    {setting.data?.first_upgrade_notice && <div className="permission-upgrade-note">{zh ? "AI Team OS 现在支持三种权限模式。已为你选择推荐的标准模式，你可以随时修改。" : "AI Team OS now supports three permission modes. Recommended Standard mode is selected; you can change it anytime."}</div>}
    <div className="permission-card-grid">
      {MODES.map(({ mode, icon: Icon, zh: titleZh, en, descZh, descEn, fitZh, fitEn }) => <article key={mode} className={`permission-card ${setting.data?.mode === mode ? "selected" : ""}`}><div className="permission-card-title"><Icon size={21}/><h3>{zh ? titleZh : en}</h3>{mode === "standard" && <span className="recommended">{zh ? "推荐" : "Recommended"}</span>}</div><p>{zh ? descZh : descEn}</p><small>{zh ? "适合：" : "Best for: "}{zh ? fitZh : fitEn}</small><button className={setting.data?.mode === mode ? "btn on" : "btn"} disabled={save.isPending || setting.data?.mode === mode} onClick={() => choose(mode)}>{setting.data?.mode === mode ? (zh ? "当前模式" : "Current mode") : (zh ? `启用${titleZh}` : `Enable ${en}`)}</button></article>)}
    </div>
    {confirmMaximum && <div className="maximum-confirm" role="dialog" aria-modal="true" aria-label={zh ? "确认最高权限模式" : "Confirm Maximum mode"}><div className="maximum-confirm-card"><h3>{zh ? "启用最高权限模式" : "Enable Maximum Permissions"}</h3><p>{zh ? "AI Team OS 将自动修改和删除普通文件、控制应用窗口、运行项目工具，并完成代码修改与测试。" : "AI Team OS may automatically modify or delete normal files, control apps, run project tools, and complete code changes and tests."}</p><p>{zh ? "密码、密钥、UAC、安全系统和 STOP 等核心边界仍不可绕过。" : "Passwords, secrets, UAC, the safety kernel, and STOP remain protected."}</p><div className="button-row"><button onClick={() => setConfirmMaximum(false)}>{zh ? "取消" : "Cancel"}</button><button className="btn btn-primary" onClick={() => save.mutate({ mode: "maximum", confirmed: true })}>{zh ? "启用最高权限" : "Enable Maximum"}</button></div></div></div>}
    {message && <p className="muted" role="status">{message}</p>}
    <details className="permission-history"><summary>{zh ? "最近自动操作" : "Recent Automatic Actions"}</summary>{history.data?.actions.length ? <div className="permission-history-list">{history.data.actions.slice(0, 20).map((item) => <div key={item.action_id}><time>{new Date(item.timestamp).toLocaleTimeString()}</time><span className={`permission-badge ${item.permission_mode}`}>{item.permission_mode}</span><strong>{item.action}</strong><small>{item.target || item.reason}</small></div>)}</div> : <p className="muted">{zh ? "尚无自动操作。" : "No automatic actions yet."}</p>}</details>
  </section>;
}
