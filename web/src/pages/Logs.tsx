// Logs（010 二十四）：结构化事件视图（可筛选）
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { subscribeEvents } from "../api/client";

export function Logs() {
  const [events, setEvents] = useState<import("../api/types").RuntimeEvent[]>([]);
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const firstRun = (tasks.data ?? [])[0]?.run_id;
  const [filter, setFilter] = useState("");

  useQuery({
    queryKey: ["logs-raw", firstRun],
    queryFn: async () => {
      if (!firstRun) return [];
      return [];
    },
    enabled: false,
  });

  // 简单 SSE 订阅最新任务事件作为结构化日志
  useMemo(() => {
    if (!firstRun) return;
    const close = subscribeEvents(firstRun, (ev) => {
      setEvents((prev) => [...prev.slice(-499), ev]);
    });
    return () => close();
  }, [firstRun]);

  const filtered = events.filter(
    (e) =>
      !filter ||
      e.event_type.includes(filter) ||
      (e.actor_type ?? "").includes(filter) ||
      e.summary.includes(filter),
  );

  return (
    <div className="page">
      <h1>Logs</h1>
      <div className="card">
        <input
          className="filter-input"
          placeholder="Filter: event type / actor / text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="feed">
          {filtered.map((e) => (
            <div key={e.event_id} className="feed-item">
              <span className="feed-time">{e.timestamp}</span>
              <span className="feed-actor">{e.actor_type}</span>
              <span className="feed-type">{e.event_type}</span>
              <span className="feed-summary">{e.summary}</span>
            </div>
          ))}
          {filtered.length === 0 && <p className="muted">No events (SSE live tail).</p>}
        </div>
      </div>
    </div>
  );
}
