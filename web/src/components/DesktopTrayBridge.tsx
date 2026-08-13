import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";

type TrayAction = "pause_jarvis" | "stop_computer" | "toggle_voice" | "settings";

async function handleTrayAction(action: TrayAction, navigate: (path: string) => void) {
  if (action === "settings") {
    navigate("/settings");
    return;
  }
  if (action === "stop_computer") {
    await api.stopComputer();
    return;
  }
  if (action === "toggle_voice") {
    const status = await api.voice();
    await (status.session_active ? api.stopVoice() : api.startVoice());
    return;
  }
  await Promise.allSettled([api.pauseVoice(), api.pauseComputer()]);
}

export function DesktopTrayBridge() {
  const navigate = useNavigate();

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/event").then(async ({ listen }) => {
      const remove = await listen<string>("desktop-tray-action", (event) => {
        if (disposed) return;
        void handleTrayAction(event.payload as TrayAction, navigate).catch(() => undefined);
      });
      if (disposed) remove();
      else unlisten = remove;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [navigate]);

  return null;
}
