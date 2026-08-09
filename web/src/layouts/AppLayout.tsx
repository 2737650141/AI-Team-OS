import {
  Activity,
  Bot,
  FileText,
  FolderKanban,
  Gauge,
  KeyRound,
  ListTodo,
  MonitorCog,
  ScrollText,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Wrench,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { useI18n } from "../i18n";
import type { Lang } from "../i18n";

export function AppLayout() {
  const { lang, setLang, t } = useI18n();
  const NAV = [
    { to: "/", label: t("nav.dashboard"), icon: Gauge },
    { to: "/tasks", label: t("nav.tasks"), icon: ListTodo },
    { to: "/computer", label: t("nav.computer"), icon: MonitorCog },
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
