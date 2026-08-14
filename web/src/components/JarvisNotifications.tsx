import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";

const NOTIFIED_PREFIX = "ai-team-os.notification.";
const FOCUS_RUN_KEY = "ai-team-os.jarvis-focus-run";

export function JarvisNotifications() {
  const navigate = useNavigate();
  const settings = useQuery({ queryKey: ["interaction-settings"], queryFn: api.interactionSettings });
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 5000 });

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    let disposed = false;
    let remove: (() => void) | undefined;
    void import("@tauri-apps/plugin-notification").then(async ({ onAction }) => {
      const listener = await onAction((notification) => {
        const runId = String(notification.extra?.run_id ?? "");
        if (runId) window.localStorage.setItem(FOCUS_RUN_KEY, runId);
        navigate("/");
      });
      if (disposed) listener.unregister();
      else remove = () => listener.unregister();
    }).catch(() => {
      // Notifications are best-effort and must never destabilize the workspace.
    });
    return () => { disposed = true; remove?.(); };
  }, [navigate]);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window) || !settings.data) return;
    for (const task of dashboard.data?.recent_tasks ?? []) {
      const kind = task.status === "completed" ? "completed" : task.status === "failed" ? "failed" : task.status === "paused" && (dashboard.data?.metrics.pending_approvals ?? 0) > 0 ? "approval" : null;
      if (!kind) continue;
      if (kind === "completed" && !settings.data.notify_completed) continue;
      if (kind === "failed" && !settings.data.notify_failed) continue;
      if (kind === "approval" && !settings.data.notify_approval) continue;
      const key = `${NOTIFIED_PREFIX}${task.run_id}.${kind}`;
      if (window.localStorage.getItem(key)) continue;
      window.localStorage.setItem(key, "1");
      void notifyTask(task.run_id, task.goal, kind);
    }
  }, [dashboard.data, settings.data]);

  return null;
}

async function notifyTask(runId: string, goal: string, kind: "completed" | "failed" | "approval") {
  const { isPermissionGranted, requestPermission, sendNotification } = await import("@tauri-apps/plugin-notification");
  let granted = await isPermissionGranted();
  if (!granted) granted = (await requestPermission()) === "granted";
  if (!granted) return;
  const body = kind === "completed" ? `${goal} 已完成` : kind === "failed" ? `${goal} 遇到问题` : `${goal} 需要你的确认`;
  sendNotification({ title: "AI Team OS · JARVIS", body, extra: { run_id: runId }, autoCancel: true });
}
