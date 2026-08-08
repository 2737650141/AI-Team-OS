import { useEffect, useRef, useState } from "react";

import { subscribeEvents } from "../api/client";
import type { RuntimeEvent } from "../api/types";

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
      ref.current = [...ref.current, ev];
      setEvents(ref.current);
    }, () => setConnected(false));
    setConnected(true);
    return close;
  }, [runId, enabled]);

  return { events, connected };
}
