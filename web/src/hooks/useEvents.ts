import { useEffect, useRef, useState } from "react";

import { subscribeEvents } from "../api/client";
import type { RuntimeEvent } from "../api/types";
import { rememberRuntimeEvent } from "../runtime/diagnostics";

export const MAX_VISIBLE_RUNTIME_EVENTS = 300;

// SSE 实时事件 Hook（010 二十四）：事件流 + 连接状态
export function useEvents(runId: string | undefined, enabled = true) {
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const ref = useRef<RuntimeEvent[]>([]);

  useEffect(() => {
    if (!runId || !enabled) return;
    ref.current = [];
    setEvents([]);
    const close = subscribeEvents(runId, (ev) => {
      if (ref.current.some((item) => item.event_id === ev.event_id)) return;
      rememberRuntimeEvent(ev.event_id);
      ref.current = [...ref.current, ev].slice(-MAX_VISIBLE_RUNTIME_EVENTS);
      setEvents(ref.current);
    }, () => setConnected(false));
    setConnected(true);
    return close;
  }, [runId, enabled]);

  return { events, connected };
}
