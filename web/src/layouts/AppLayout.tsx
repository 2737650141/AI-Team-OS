import {
  Activity,
  Bot,
  FileText,
  FolderKanban,
  Gauge,
  KeyRound,
  ListTodo,
  ScrollText,
  Settings,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

const NAV = [
  { to: "/", label: "Dashboard", icon: Gauge },
  { to: "/tasks", label: "Tasks", icon: ListTodo },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/approvals", label: "Approvals", icon: ShieldCheck },
  { to: "/evidence", label: "Evidence", icon: FileText },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/memory", label: "Memory", icon: FolderKanban },
  { to: "/logs", label: "Logs", icon: ScrollText },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AppLayout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Activity size={18} />
          <div>
            <strong>AI Team OS</strong>
            <span>Control Center</span>
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
          <span>Local · 127.0.0.1</span>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
