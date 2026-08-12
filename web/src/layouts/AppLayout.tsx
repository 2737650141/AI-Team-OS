import {
  Activity,
  Bot,
  FileText,
  FolderKanban,
  Gauge,
  KeyRound,
  ListTodo,
  MonitorCog,
  Mic,
  ScrollText,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Wrench,
  BarChart3,
} from "lucide-react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { useI18n } from "../i18n";
import type { Lang } from "../i18n";

export function AppLayout() {
  const { lang, setLang, t } = useI18n();
  const permission = useQuery({ queryKey: ["permission-mode"], queryFn: api.permissionMode, refetchInterval: 5000 });
  const activeContext = useQuery({ queryKey: ["active-context"], queryFn: api.activeContext, refetchInterval: 4000 });
  const NAV = [
    { to: "/", label: t("nav.dashboard"), icon: Gauge },
    { to: "/tasks", label: t("nav.tasks"), icon: ListTodo },
    { to: "/computer", label: t("nav.computer"), icon: MonitorCog },
    { to: "/usage", label: lang === "zh" ? "用量与上下文" : "Usage & Context", icon: BarChart3 },
    { to: "/voice", label: lang === "zh" ? "语音交互" : "Voice", icon: Mic },
    { to: "/agents", label: t("nav.agents"), icon: Bot },
    { to: "/approvals", label: t("nav.approvals"), icon: ShieldCheck },
    { to: "/evidence", label: t("nav.evidence"), icon: FileText },
    { to: "/tools", label: t("nav.tools"), icon: Wrench },
    { to: "/memory", label: t("nav.memory"), icon: FolderKanban },
    { to: "/personalization", label: lang === "zh" ? "个性化" : "Personalization", icon: SlidersHorizontal },
    { to: "/logs", label: t("nav.logs"), icon: ScrollText },
    { to: "/settings", label: t("nav.settings"), icon: Settings },
  ];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Activity size={18} />
          <div>
            <strong>AI Team OS</strong>
            <span>{t("brand.controlCenter")}</span>
          </div>
        </div>
        <nav>
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
            >
              <Icon size={16} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <KeyRound size={14} />
          <span>{t("brand.local")}</span>
        </div>
      </aside>
      <main className="main">
        {activeContext.data?.active && activeContext.data.context?.percentage !== null && <Link className="active-context-badge" to={`/usage?run=${activeContext.data.run_id}`}><span>Context</span><strong>{Math.round((activeContext.data.context?.percentage ?? 0) * 100)}%</strong>{(activeContext.data.context?.percentage ?? 0) >= .8 && <em>· Compacting</em>}</Link>}
        <Link className={`global-permission-badge ${permission.data?.mode ?? "standard"}`} to="/settings#security-permissions">{lang === "zh" ? `权限：${permission.data?.mode === "maximum" ? "最高" : permission.data?.mode === "safe" ? "安全" : "标准"}` : `Permissions: ${permission.data?.mode ?? "standard"}`}</Link>
        {/* 右上角语言切换（010-B 九）：简体中文 / English */}
        <div className="lang-switch" title={t("lang.label")}>
          <button
            className={lang === "zh" ? "lang-btn on" : "lang-btn"}
            onClick={() => setLang("zh" as Lang)}
          >
            简体中文
          </button>
          <button
            className={lang === "en" ? "lang-btn on" : "lang-btn"}
            onClick={() => setLang("en" as Lang)}
          >
            English
          </button>
        </div>
        <Outlet />
      </main>
    </div>
  );
}
