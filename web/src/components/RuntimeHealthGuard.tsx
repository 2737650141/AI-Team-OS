import { useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import { RuntimeRecoveryView } from "./RuntimeRecoveryView";

const HEALTH_INTERVAL_MS = 5000;
const FAILURE_THRESHOLD = 2;

async function heartbeat() {
  if (!("__TAURI_INTERNALS__" in window)) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("frontend_heartbeat", { timestamp: new Date().toISOString() });
  } catch { /* heartbeat is diagnostic-only */ }
}

export function RuntimeHealthGuard({ children }: { children: ReactNode }) {
  const [disconnected, setDisconnected] = useState(false);

  useEffect(() => {
    let stopped = false;
    let failures = 0;
    const check = async () => {
      await heartbeat();
      try {
        await api.health();
        failures = 0;
        if (!stopped) setDisconnected(false);
      } catch {
        failures += 1;
        if (!stopped && failures >= FAILURE_THRESHOLD) setDisconnected(true);
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), HEALTH_INTERVAL_MS);
    return () => { stopped = true; window.clearInterval(timer); };
  }, []);

  if (disconnected) return <RuntimeRecoveryView kind="core" />;
  return children;
}
