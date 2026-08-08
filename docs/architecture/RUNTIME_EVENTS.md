# Runtime Events（010 十三/十四/二十五）

## RuntimeEvent

```text
event_id  task_id  run_id  timestamp  sequence  event_type
actor_type  actor_id  summary  payload_safe
```

- `sequence` 单调递增（SQLite AUTOINCREMENT）。
- `payload_safe` 逐字段经 `redact()` 脱敏——**严禁**写入 API Key/Token/隐藏推理。

## EventStore

`app/core/events.py`：

- SQLite 持久化：`runtime/events.sqlite`（Git 忽略）。
- `emit(...)`：校验事件类型 + 深脱敏 payload + 落库。
- `list_events(run_id, after_sequence)`：按 run_id 查询 / replay。
- 进程级单例：`events.init(data_dir)` 后 runner/graph/gateway/executor 复用。

## 事件类型（010 二十四）

```text
task_created  task_status_changed  task_completed  task_failed
plan_created
subtask_started  subtask_completed
agent_started  agent_completed  agent_failed
model_call_started  model_call_completed
tool_started  tool_completed  tool_blocked
evidence_created
approval_requested  approval_approved  approval_rejected
patch_created  patch_applied
test_started  test_completed
review_started  review_passed  review_rejected
rework_started
```

## 埋点位置

- `runner`：task_created / task_status_changed（paused）/ task_completed / task_failed。
- `graph`：plan_created / subtask_started / subtask_completed / review_passed /
  review_rejected / rework_started。
- `executor`：approval_requested / patch_applied / test_started / test_completed。
- `tool_gateway`：tool_started / tool_completed / tool_blocked（携带 run_id）。

## SSE

`GET /tasks/{run_id}/events`（text/event-stream）：

- 轮询 EventStore（sequence > last），无新事件发 `: keepalive` 心跳。
- 任务终态（completed/failed）补发状态事件后关闭连接。
- 支持 `Last-Event-ID` 语义（`?after=` + id 行）。
- 前端 `useEvents` 断线自动重连（1.5s 退避）。

## 刷新恢复（010 十五/二十六）

浏览器刷新后重新拉取：`GET /tasks/{run_id}` + `/events` + `/evidence` +
`/artifacts` + `/approvals`；React 内存不是关键状态唯一来源。
