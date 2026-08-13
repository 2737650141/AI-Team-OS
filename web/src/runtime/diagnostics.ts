let lastEventId: string | null = null;

export function rememberRuntimeEvent(eventId: string) { lastEventId = eventId; }

export async function reportFrontendError(errorType: string, message: string, component = "") {
  const redact = (value: string, max: number) => value
    .replace(/(token|key|password|secret)=([^\s&]+)/gi, "$1=[redacted]")
    .slice(0, max);
  const taskId = window.location.pathname.match(/^\/tasks\/([^/]+)/)?.[1] ?? null;
  const diagnostic = {
    error_type: errorType,
    message: redact(message, 500),
    component: redact(component, 1000),
    route: window.location.pathname,
    timestamp: new Date().toISOString(),
    task_id: taskId,
    last_event_id: lastEventId,
  };
  try {
    if ("__TAURI_INTERNALS__" in window) {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("write_frontend_diagnostic", { diagnostic });
    }
  } catch { /* diagnostics must never create a second application failure */ }
}

export function installGlobalErrorCapture() {
  window.addEventListener("error", (event) => void reportFrontendError("window_error", event.message));
  window.addEventListener("unhandledrejection", (event) => {
    const message = event.reason instanceof Error ? event.reason.message : String(event.reason);
    void reportFrontendError("unhandled_rejection", message);
  });
}
