import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { api } from "./api/client";
import { AppLayout } from "./layouts/AppLayout";
import { Agents } from "./pages/Agents";
import { Dashboard } from "./pages/Dashboard";
import { Evidence } from "./pages/Evidence";
import { Logs } from "./pages/Logs";
import { Memory } from "./pages/Memory";
import { Setup } from "./pages/Setup";
import { Settings } from "./pages/Settings";
import { TaskDetail } from "./pages/TaskDetail";
import { Tasks } from "./pages/Tasks";
import { Tools } from "./pages/Tools";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 2000 } },
});

// Approvals 中心（010 十六）：指向最新任务的审批（简化导航）
function ApprovalsRedirect() {
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const runId = tasks.data?.[0]?.run_id;
  if (runId) return <Navigate to={`/tasks/${runId}`} replace />;
  return <div className="page">No approvals yet.</div>;
}

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/tasks/:runId" element={<TaskDetail />} />
            <Route path="/approvals" element={<ApprovalsRedirect />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/evidence" element={<Evidence />} />
            <Route path="/tools" element={<Tools />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
          <Route path="/setup" element={<Setup />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

