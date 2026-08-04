# AI Team OS 统一任务状态模型草案

> 文档状态：Phase 0 草案，待总管验收
> 版本：v0.1（2026-08-04）

## 1. 设计原则

1. **单一状态源**：整个任务的唯一状态存在于 LangGraph `State`（经 Checkpointer 持久化）。API、前端、各服务只读快照，不另存副本。
2. **权威写入路径**：每个字段或子字段只有一个权威写入路径；多来源事件（tool_calls、evidence、review_history 等）通过确定性 reducer 追加，不互相覆盖。
3. **追加不覆盖**：事件类字段（tool_calls、evidence、approvals、errors）只追加；结果类字段由所有者以"写新版本 + 保留旧值"方式更新，禁止整字段覆盖。
4. **并发安全**：LangGraph 节点在同一任务内串行推进；并行子任务写不同子字段（`subtasks[i]`），由状态 reducer 合并，避免互相覆盖。

## 2. 字段定义

| 字段 | 类型 | 写入者(Owner) | 可修改者 | 说明 |
| -- | -- | -- | -- | -- |
| `task_id` | str | API 层（创建时） | 任何人只读 | 全局唯一，UUID |
| `project_id` | str | API 层 | 任何人只读 | 项目/记忆命名空间 |
| `user_goal` | str | API 层 | 任何人只读 | 用户原始输入，不可变 |
| `clarified_goal` | str | Supervisor | 仅 Supervisor（澄清轮次内） | 澄清后的目标；每次澄清生成新版本 |
| `constraints` | list[str] | Supervisor（澄清） | Supervisor | 追加式，LLM 不得自行删除用户约束 |
| `plan` | Plan | Planner | 仅 Supervisor（因约束变化而重新规划时） | 结构化计划：子任务依赖图 |
| `subtasks` | list[Subtask] | 按子字段拆分（见 §3.5） | 按子字段授权 | 至少拆分 `spec / runtime_status / execution_result / review_history` 四部分，各有一个权威写入路径 |
| `selected_agents` | dict[subtask_id, agent_id] | Supervisor | Supervisor | 派发记录，追加式 |
| `evidence` | list[Evidence] | Tool Gateway（工具结果快照） | 任何人只读 | `{id, subtask_id, tool, summary, artifact_ref, ts}` |
| `artifacts` | list[Artifact] | Executor / Tool Gateway | 任何人只读 | 产物引用（沙箱路径、类型、哈希） |
| `approvals` | list[Approval] | Permission & Approval Service | 仅人工（批准/拒绝） | `{id, tool, args_summary, status, decided_by, ts}` |
| `tool_calls` | list[ToolCallRecord] | Tool Gateway | 任何人只读 | 追加式：每次调用的完整审计记录 |
| `token_budget` | int | API 层（创建任务时） | 仅用户审批后由 API 层修改；对 LLM 不可修改 | 任务总 Token 预算（冻结规则见 §3.6） |
| `cost_budget` | float | API 层（创建任务时） | 仅用户审批后由 API 层修改；对 LLM 不可修改 | 任务总成本预算（美元），冻结规则同 token_budget |
| `budget_usage` | dict | Model Gateway（唯一权威记账入口） | 任何人只读 | 累计 token/cost，实时累加；工具调用成本也经 Model Gateway 记账器累加 |
| `subtask_budget_allocations` | dict[subtask_id, int] | Planner | 任何人只读 | Planner 对子任务的预算分配；总和不得超过任务总预算 |
| `checkpoint_version` | str | LangGraph Checkpointer | 任何人只读 | Checkpoint schema 版本号，恢复时校验（R18） |
| `failure_code` | str | 状态机/确定性节点 | 任何人只读 | 独立错误原因码（如 `loop_detected`、`budget_exceeded`），与 `current_status=failed` 分离保存 |
| `paused_from_status` | str | 状态机 | 任何人只读 | 暂停前的状态值，恢复时还原（仅 paused 期间有效） |
| `idempotency_keys` | list[str] | Tool Gateway / 确定性节点 | 任何人只读 | 工具调用与事件写入的幂等键，防恢复/并发重放重复执行（R19） |
| `retry_count` | int | Supervisor | Supervisor | 返工轮次计数，超阈值转人工 |
| `review_result` | ReviewResult | Reviewer | 任何人只读 | pass / reject + 定向意见 |
| `errors` | list[ErrorRecord] | 各节点（异常捕获处） | 任何人只读 | 追加式：`{node, code, message, retryable, ts}` |
| `final_result` | str/Artifact | Supervisor（finalize） | 任何人只读 | 最终交付物 |
| `memory_candidates` | list[MemoryCandidate] | Supervisor（finalize） | 仅人工确认（或确定性过滤规则） | 待写入 Memory Service 的候选 |
| `current_status` | str | LangGraph 状态机 | 任何人只读 | 枚举（统一 12 值）：`created / clarifying / clarified / planning / dispatching / executing / awaiting_approval / reviewing / reworking / paused / completed / failed` |

## 3. 写入者与冲突规避

### 3.1 为什么需要权威写入路径
多智能体共享同一状态时，若无所有权约束，会出现：两个节点同时写 `final_result`、Reviewer 覆盖 Executor 的产出、LLM 误改约束。解决方式是**代码层强制权威写入路径**（允许一个字段有多个来源，但必须经确定性 reducer 追加，禁止直接覆盖）：

- LangGraph 节点函数只接收 `State` 的只读视图 + 自己拥有的字段句柄；用 TypedDict 类型约束 + 运行时校验（Pydantic）双重把关。
- 每个节点声明 `writes: set[str]`，图执行前校验与字段所有权表一致，不一致直接启动失败（fail-fast）。

### 3.2 并行子任务的数据隔离
- 并行 Executor 节点各自持有 `subtasks[i]` 与 `evidence[i-前缀]` 的写入权，按**子任务 ID 分片**，reducer 按 `(subtask_id, key)` 合并，天然无冲突。
- 共享只读字段（`plan`、`constraints`、`budget_usage`）用原子累加器（工具网关内锁/数据库原子更新）写入，禁止"读-改-写"整字段。

### 3.3 追加 vs 覆盖规则
- 追加（append-only，经确定性 reducer）：`tool_calls`、`evidence`、`errors`、`approvals`、`selected_agents`、`subtasks[].review_history`。
- 版本化更新：`clarified_goal`、`review_result`（每次返工追加一条评审记录，不覆盖历史）。
- 唯一可覆盖：`current_status`（状态机独占）；`runtime_status`（状态机写入）。
- 所有 LLM 输出先经过 Schema 校验（Pydantic），**不能直接覆盖 RuntimeState**；LLM 只能提交 proposal，由确定性节点校验后写入。

### 3.5 subtasks 子字段拆分

```text
subtasks[].spec               ← 仅 Planner 写入（创建时）
subtasks[].runtime_status     ← 仅状态机写入（created/dispatching/executing/reviewing/…）
subtasks[].execution_result   ← Executor 只能提交 execution result proposal，由确定性节点校验后写入
subtasks[].review_history     ← 仅 Reviewer 追加（每次评审一条，不覆盖）
```

Tool Gateway 只追加 `tool_calls` 和 `evidence`（不写其他字段）。

### 3.6 预算冻结规则（002-A）

1. 任务总预算（`token_budget`、`cost_budget`）由 API/用户创建任务时写入。
2. 创建后对 LLM 不可修改（Planner、Supervisor、任何 agent 均无修改权）。
3. Planner 只能产生 `subtask_budget_allocations`，其总和不得超过任务总预算（确定性校验）。
4. Supervisor 只能选择继续、降级、暂停或停止，不得修改预算本身。
5. 增加任务总预算必须经过用户审批（API 层执行）。
6. Model Gateway 是预算使用量的唯一权威记账入口。

### 3.4 中断与恢复
- 澄清、审批、暂停均通过 LangGraph `interrupt` 实现：状态已持久化，恢复时从断点继续，`current_status` 由状态机恢复为原值。
- 恢复后校验：`budget_usage`、`retry_count` 等计数器不因恢复而重置（存储于 checkpoint，非内存）。

## 4. 状态流转

统一状态枚举（12 值）：`created / clarifying / clarified / planning / dispatching / executing / awaiting_approval / reviewing / reworking / paused / completed / failed`

```text
created → clarifying ⇄ clarified
clarified → planning → dispatching
dispatching → executing（并行子图）
executing ⇄ awaiting_approval（审批挂起）
executing → reviewing
reviewing → reworking → dispatching（定向返工，retry_count+1）
reviewing → completed（全部通过）
executing/reviewing → failed（不可恢复错误或超限）
任意状态 → paused（用户暂停，记录 paused_from_status）→ 原状态（恢复）
```

`current_status` 转换只允许按上图边迁移，由状态机代码强制执行（LLM 无权限）。**错误原因独立保存于 `failure_code`**（如 `loop_detected`、`budget_exceeded`、`schema_invalid`）；禁止把 `failed(loop_detected)` 等带原因的写法当作状态值。

## 5. 与数据库的映射（M2 落地）

- checkpoint 表：LangGraph 官方 schema（SQLite/Postgres）。
- 业务表：`tasks`（task_id 主键，存状态 JSON 摘要）、`subtasks`、`evidence`、`approvals`、`tool_calls`、`memory`。
- 状态 JSON 为单一事实源；业务表为查询/审计索引，从状态事件流派生，**不允许反向写回状态**。
