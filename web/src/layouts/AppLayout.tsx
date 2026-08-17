import {
  Activity,
  Bot,
  ChevronDown,
  ChevronRight,
  FolderKanban,
  KeyRound,
  ListTodo,
  MessageSquarePlus,
  Mic,
  MonitorCog,
  ScrollText,
  Settings,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { useI18n } from "../i18n";
import type { Lang } from "../i18n";

const SESSION_KEY = "ai-team-os.jarvis-session";

function currentSessionId(): string {
  const value = window.localStorage.getItem(SESSION_KEY) ?? "jarvis-desktop";
  window.localStorage.setItem(SESSION_KEY, value);
  return value;
}

// Control Center 收纳的既有页面（不删除路由，仅导航收纳）
const CONTROL_CENTER_PAGES = [
  { to: "/tasks", label: "nav.tasks", icon: ListTodo },
  { to: "/agents", label: "nav.agents", icon: Bot },
  { to: "/approvals", label: "nav.approvals", icon: ShieldCheck },
  { to: "/evidence", label: "nav.evidence", icon: Activity },
  { to: "/usage", label: "nav.usage", icon: Activity },
  { to: "/memory", label: "nav.memory", icon: FolderKanban },
  { to: "/tools", label: "nav.tools", icon: Bot },
  { to: "/logs", label: "nav.logs", icon: ScrollText },
];

export function AppLayout() {
  const { lang, setLang, t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const [controlCenterOpen, setControlCenterOpen] = useState(() =>
    CONTROL_CENTER_PAGES.some(({ to }) => location.pathname.startsWith(to)),
  );
  const permission = useQuery({ queryKey: ["permission-mode"], queryFn: api.permissionMode, refetchInterval: 5000 });
  const activeContext = useQuery({ queryKey: ["active-context"], queryFn: api.activeContext, refetchInterval: 4000 });
  const sessions = useQuery({ queryKey: ["jarvis-sessions"], queryFn: api.jarvisSessions, refetchInterval: 15000 });
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 15000 });
  const projects = [...new Set((dashboard.data?.recent_tasks ?? []).map((task) => task.project_id || "default"))].slice(0, 8);
  const recent = sessions.data?.sessions ?? [];
  const newConversation = useMutation({
    mutationFn: () => api.clearJarvisSession(currentSessionId()),
    onSuccess: (session) => {
      qc.setQueryData(["jarvis-session", session.session_id], session);
      void qc.invalidateQueries({ queryKey: ["jarvis-sessions"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      navigate("/");
    },
  });

  return (
    <div className="app-shell app-shell-three">
      <aside className="sidebar sidebar-left">
        <div className="brand">
          <Sparkles size={17} />
          <div>
            <strong>AI Team OS</strong>
            <span>{t("brand.controlCenter")}</span>
          </div>
        </div>

        <button
          className="new-conversation-btn"
          onClick={() => newConversation.mutate()}
          disabled={newConversation.isPending}
        >
          <MessageSquarePlus size={15} />
          {lang === "zh" ? "新对话" : "New conversation"}
        </button>

        <nav className="left-nav">
          <div className="left-nav-group project-nav-group">
            <span className="left-nav-label">{lang === "zh" ? "项目" : "Projects"}</span>
            {projects.length === 0 ? (
              <span className="left-nav-empty">{lang === "zh" ? "暂无项目" : "No projects yet"}</span>
            ) : (
              projects.map((project) => (
                <NavLink key={project} to={`/?project=${encodeURIComponent(project)}`} className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}>
                  <FolderKanban size={15} />
                  <span className={`nav-project-name ${project === "default" ? "is-default" : ""}`}>{project}</span>
                </NavLink>
              ))
            )}
          </div>

          <div className="left-nav-group recent-nav-group">
            <span className="left-nav-label">{lang === "zh" ? "最近对话" : "Recent conversations"}</span>
            {recent.length === 0 ? (
              <span className="left-nav-empty">{lang === "zh" ? "暂无对话" : "No conversations yet"}</span>
            ) : (
              recent.slice(0, 6).map((session) => (
                <NavLink key={session.session_id} to={`/?session=${encodeURIComponent(session.session_id)}`} className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}>
                  <MessageSquarePlus size={15} />
                  <span className="nav-item-text">{session.current_goal || session.last_summary || session.session_id}</span>
                </NavLink>
              ))
            )}
          </div>

          <div className="left-nav-group">
            <button
              className="nav-item control-center-toggle"
              type="button"
              aria-expanded={controlCenterOpen}
              onClick={() => setControlCenterOpen((open) => !open)}
            >
              {controlCenterOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
              <span>{lang === "zh" ? "控制中心" : "Control Center"}</span>
            </button>
            {controlCenterOpen && (
              <div className="control-center-pages">
                {CONTROL_CENTER_PAGES.map(({ to, label, icon: Icon }) => (
                  <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}>
                    <Icon size={15} />
                    <span>{t(label)}</span>
                  </NavLink>
                ))}
              </div>
            )}
          </div>

          <div className="left-nav-group">
            <NavLink to="/settings" className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}>
              <Settings size={15} />
              <span>{t("nav.settings")}</span>
            </NavLink>
          </div>
        </nav>

        <div className="sidebar-foot">
          <KeyRound size={14} />
          <span>{t("brand.local")}</span>
        </div>
      </aside>

      <main className="main main-center">
        <div className="top-right-actions top-quick-status" aria-label={lang === "zh" ? "快捷操作" : "Quick actions"}>
          <Link className={`global-permission-badge ${permission.data?.mode ?? "standard"}`} to="/settings#security-permissions">{lang === "zh" ? `权限：${permission.data?.mode === "maximum" ? "最高" : permission.data?.mode === "safe" ? "安全" : "标准"}` : `Permissions: ${permission.data?.mode ?? "standard"}`}</Link>
          <Link className="quick-status-link" to="/computer" title={lang === "zh" ? "电脑控制" : "Computer control"}><MonitorCog size={14} />{lang === "zh" ? "电脑" : "Computer"}</Link>
          <Link className="quick-status-link" to="/voice" title="Voice"><Mic size={14} />{lang === "zh" ? "语音" : "Voice"}</Link>
          {activeContext.data?.active && activeContext.data.context?.percentage !== null && <Link className="active-context-badge" to={`/usage?run=${activeContext.data.run_id}`}><span>Context</span><strong>{Math.round((activeContext.data.context?.percentage ?? 0) * 100)}%</strong>{(activeContext.data.context?.percentage ?? 0) >= .8 && <em>· Compacting</em>}</Link>}
          <div className="lang-switch" title={t("lang.label")}>
            <button className={lang === "zh" ? "lang-btn on" : "lang-btn"} onClick={() => setLang("zh" as Lang)}>简体中文</button>
            <button className={lang === "en" ? "lang-btn on" : "lang-btn"} onClick={() => setLang("en" as Lang)}>English</button>
          </div>
        </div>
        <Outlet />
      </main>
    </div>
  );
}
