import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { api } from "./api/client";
import { I18nProvider, useI18n } from "./i18n";
import { AppLayout } from "./layouts/AppLayout";
import { RuntimeHealthGuard } from "./components/RuntimeHealthGuard";
import { Agents } from "./pages/Agents";
import { Dashboard } from "./pages/Dashboard";
import { Computer } from "./pages/Computer";
import { Evidence } from "./pages/Evidence";
import { Logs } from "./pages/Logs";
import { Memory } from "./pages/Memory";
import { Personalization } from "./pages/Personalization";
import { Setup } from "./pages/Setup";
import { Settings } from "./pages/Settings";
import { TaskDetail } from "./pages/TaskDetail";
import { Tasks } from "./pages/Tasks";
import { Tools } from "./pages/Tools";
import { Voice } from "./pages/Voice";
import { Usage } from "./pages/Usage";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 2000 } },
});

// Approvals 中心（010 十六）：指向最新任务的审批（简化导航）
function ApprovalsRedirect() {
  const { t } = useI18n();
  const pending = useQuery({ queryKey: ["pending-approval-run"], queryFn: api.pendingApprovalRun });
  const runId = pending.data;
  if (runId) return <Navigate to={`/tasks/${runId}`} replace />;
  return <div className="page">{t("ap.required")}</div>;
}

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <I18nProvider>
        <RuntimeHealthGuard><BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/tasks" element={<Tasks />} />
              <Route path="/computer" element={<Computer />} />
              <Route path="/voice" element={<Voice />} />
              <Route path="/tasks/:runId" element={<TaskDetail />} />
              <Route path="/usage" element={<Usage />} />
              <Route path="/approvals" element={<ApprovalsRedirect />} />
              <Route path="/agents" element={<Agents />} />
              <Route path="/evidence" element={<Evidence />} />
              <Route path="/tools" element={<Tools />} />
              <Route path="/logs" element={<Logs />} />
              <Route path="/memory" element={<Memory />} />
              <Route path="/personalization" element={<Personalization />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
            <Route path="/setup" element={<Setup />} />
          </Routes>
        </BrowserRouter></RuntimeHealthGuard>
      </I18nProvider>
    </QueryClientProvider>
  );
}

