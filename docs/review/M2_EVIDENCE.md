# M2 证据文档（docs/review/M2_EVIDENCE.md）

对应总管令 004（M2：基于 LangGraph 的确定性多智能体协作内核）。生成于本分支
`phase-2/deterministic-multi-agent` 实施完成后。

## 1. 交付概览

- 分支：`phase-2/deterministic-multi-agent`（自 `ccaf8dd` 创建，未在 main 直接开发）
- 唯一编排核心：LangGraph（Send fan-out/fan-in、interrupt、官方 reducer 均使用 LangGraph 原生能力）
- 新增外部依赖：无（未引入 CrewAI / OpenAI Agents SDK / MAF / MetaGPT / ChatDev）
- 新增组件：AgentRegistry、Plan/SubtaskSpec Schema + 10 项确定性校验、DeterministicFakePlanner（5 场景）、
  FakeResearcher（结构化 ResearchReport）、两层 Reviewer、定向返工、澄清 interrupt、finalize 汇总
- 继续使用：DeterministicFakeModel、Fixture 工具、SQLite Checkpoint、BudgetController、ToolGateway、AuditLog、恢复机制

## 2. M2-01 ~ M2-10 实现对照

| 编号 | 要求 | 实现 |
| --- | --- | --- |
| M2-01 | AgentSpec + AgentRegistry | `app/core/registry.py`：5 角色预注册，Executor `enabled=False` 只注册不派发；Registry 由确定性代码管理 |
| M2-02 | Plan/SubtaskSpec/Dependency + 10 项校验 | `app/core/schemas.py` + `app/core/plan_validator.py`（MAX_SUBTASKS=8 集中配置；校验失败按 PLAN_RETRY_LIMIT=2 重试后 failed/planning_invalid） |
| M2-03 | Supervisor 确定性调度 | `app/graph.py`：ingest/clarify/plan/dispatch/exec_subtask/review_all/finalize；禁止直接调工具、改预算、覆盖证据、无限重派 |
| M2-04 | DeterministicFakePlanner | `app/agents/planner.py`：5 场景（含 3 个负面校验场景） |
| M2-05 | Researcher | `app/agents/researcher.py`：repository_research / conflicting_sources_research / summarize；无证据 Claim 标记未验证；不写 final_result；工具经 ToolGateway |
| M2-06 | Reviewer 两层 | `app/agents/reviewer.py`：确定性检查 8 项 + Fake 评审；确定性失败强制 reject 不可覆盖 |
| M2-07 | 定向返工 | dispatch 只派 rejected 子任务；review_history 只追加；rework_count 递增；MAX_REWORK=2 超限 failed/rework_limit_exceeded |
| M2-08 | LangGraph 原生并行 | 条件边返回 Send + 静态 fan-in 边；subtasks 按 subtask_id 官方 reducer 分片；无自研线程池 |
| M2-09 | 澄清 interrupt | clarify 节点 interrupt(ClarificationPayload)；ClarificationPayload 拒绝空答案、不能修改预算/原始输入；MAX_CLARIFICATION_ROUNDS=3 |
| M2-10 | 最终汇总 | finalize 五条件（全部 passed + 无 pending 审批 + 预算未超 + 无错误）→ FinalReport（summary/decision/evidence_index/limitations/unverified_items/execution_summary） |

## 3. 黄金任务证据

- **GT-01 Offline**：`github_compare_team` → completed；s1/s2 并行研究 + s3 汇总；
  FinalReport.evidence_index ≥ 2 且全部 id 存在于 ToolGateway evidence；Reviewer 通过后才 finalize；0 网络请求。
- **GT-02**：`vague_goal` → ingest 判定模糊 → clarify interrupt（paused + pending_clarification_id）→
  跨进程 `resume --clarification "..."` → clarification_history 追加 1 条 + clarified_goal 生成 → completed；
  空答案/非澄清 payload/clarification_id 不匹配均拒绝；3 轮超限 → failed/information_insufficient。
- **GT-05**：`scenario:parallel`（含 langgraph_maintained 0.9 与 langgraph_abandoned 0.3 两个相反来源）→
  unverified_items 显式标记"来源矛盾"；矛盾 Claim 置信度 0.3 且带 evidence；Reviewer 验证引用存在。
- **GT-07**：stream 事件序列证据：exec_subtask×3 全部在首次 review_all 之前开始（fan-in 前开始）；
  三个子任务 execution_result 各自独立（分片无覆盖）；最终汇总包含全部结果。
- **GT-11**：`scenario:reject-once` → s1/s2 rework_count=0（已通过不重跑）、仅 s3 返工 1 次；
  s3 review_history 两条（reject→pass）历史保留；`scenario:always-reject` → failed/rework_limit_exceeded。

## 4. 测试与工具链结果（004 十八）

```text
pytest:           53 passed（M2 新增 24 + M1 回归 29；覆盖 004 十八 22 项测试要求）
Ruff format:      36 files already formatted（--check 通过）
Ruff check:       All checks passed
mypy:             Success: no issues found in 24 source files
M1 回归:          全部通过（checkpoint/runner/api/工具网关/预算/审计）
网络请求次数:      0（无网络静态检查 + fixture 全离线）
```

测试文件：tests/test_m2_registry.py（注册/禁用/未知拒绝/白名单）、test_m2_plan.py（Plan schema/DAG/循环/超预算/
未知角色/disabled/白名单/数量上限）、test_m2_workflow.py（GT-01/05/07/11 + Reviewer 不可覆盖 + 无网络）、
test_resume_integration.py（跨进程澄清恢复/空答案/类型校验）、test_runner.py（M2 语义）、
test_checkpoint.py（稳定字符串/版本/未知值拒绝）、test_api.py（四端点）。

## 5. 运行时演示（artifacts/demo/，已入源码包）

```text
gt01_github_compare_team.txt   run github_compare_team → completed（GT-01）
gt02_vague_goal_paused.txt     run vague_goal → paused（澄清 interrupt）
gt02_resume_completed.txt      resume --clarification → completed（GT-02 跨进程）
gt02_trace.json                trace：clarification_history=1、subtasks=3 全 passed
gt07_parallel_demo.txt         run scenario:parallel → completed（GT-07 fan-out/fan-in）
gt11_rework_demo.txt           run scenario:reject-once → completed（GT-11 定向返工）
```

## 6. 双重审查结论（004 十九）

- 普通 review（含一次复查）：初始 1 Blocking（重跑空产物可判 pass）+ 3 should-fix + 2 nit；
  全部修复：确定性 Reviewer 新增 `rework_empty_result` 检查；场景改显式 `scenario:` 前缀（防生产目标误触发负面场景）；
  ingest 超 3 轮直接 failed/information_insufficient（删死代码节点）；ToolGateway.invoke 全程持锁 + 锁内 `snapshot()`；
  exec 防御分支模拟 reject 语义（递增 rework_count，经返工上限收敛）；API resume RuntimeError→409。
- Security review：无 CRITICAL/HIGH；1 MEDIUM（异常路径审计脱敏缺口）已修复
  （researcher 工具失败消息经 `redact()` 后写入 unverified_items）。
- 已知 LOW（已文档化，不阻塞）：① 锁保证互斥与快照一致，但并行分支的锁获取顺序仍由线程调度决定——
  "确定性"指状态收敛、路由与结果集确定，工具调用顺序不承诺可复现；② 调工具型子任务一旦被 reject，
  幂等键导致重跑必空产物 → rework_empty_result → 收敛为 fail_rework_limit，故定向返工实际主要对
  汇总型（不调工具）子任务有效——M2 以确定性/幂等性为优先，真实模型阶段（M3+）引入新证据重跑策略。

## 7. Git 与提交

- 起始提交：ccaf8dd（main）
- 分支提交：见 `git log --oneline phase-2/deterministic-multi-agent`（提交消息按 004 二十建议组织，可合理合并）
- remote：未配置；push：未执行（004 2.3 禁止）

## 8. 安全范围核对（004 十七）

无网络访问、无真实 GitHub API、无 shell/subprocess 业务工具、无文件写入工具、无 Docker/Redis/PostgreSQL/pgvector、
无外部模型、无邮件日历、无桌面/安卓控制、未 push、未外部发布；subprocess 仅测试用于验证跨进程恢复
（不作为 Agent 工具暴露）。
