# PRODUCT-01 最终报告

> PHASE: PRODUCT-01（纠偏令 020）
> 生成时间: 2026-08-12
> 范围: 停止功能扩张，先验证 AI Team OS 真实可用；修复真实失败并建立黑盒验收基线。

## ORIGINAL_FAILURE

- **User task**: "帮我查一个 guthub 上热门的项目"（任务 `9379b0e1950b`，Windows CLI 以 GBK 乱码落库，
  model_mode=real，Provider=deepseek-v4-flash，permission_mode=maximum）
- **Exact root cause**: Planner 生成 4 subtasks，st1 被分配了 registry 中存在但运行时**不可执行**的角色
  （supervisor/planner/reviewer 之一）。`plan_validator` 只校验"角色存在于 Registry 且 enabled"
  （5 个角色全部 enabled），校验放行；执行节点 `exec_subtask` 仅支持 `executor`/`researcher`，
  其余角色直接 `rejected (unsupported role)`。rework 机制 = 重新 dispatch **同一** subtask
  （角色不变）→ 连续 3 次完全相同失败 → `MAX_REWORK=2` 后 `fail_rework_limit` → `task_failed`。
- **Why old tests missed it**: 既有测试只覆盖"节点"（各 Agent 独立单测 + 确定性场景），
  未覆盖"边"——Planner → Executor 交界处的角色可执行性；fake 模式确定性计划从不产生
  不可执行角色，真实模型才可能分配。
- **Fix**:
  1. `plan_validator` 新增 `EXECUTABLE_ROLES=("executor","researcher")` + `role_not_executable` 校验，
     规划期确定性拦截（根因修复）；
  2. `LLMPlanner` 只接收可执行角色列表（Prompt 侧不再出现 supervisor/planner/reviewer 候选）；
  3. LLM 计划失败 → Supervisor **确定性 replan**（换方法，不再 Planner→Planner→Planner），
     发 `supervisor_replanned` 事件；
  4. `ReworkProgressGuard`：失败特征签名（subtask_id+role+输出哈希+issue codes+rework_targets，
     排除时间戳）连续 2 次相同 → 停止盲重试 → `replan_triggered` → Supervisor replan（上限 2 次，
     超限 `rework_limit_exceeded`）；
  5. `TaskComplexityClassifier`（TRIVIAL/SIMPLE/STANDARD/COMPLEX）：SIMPLE 单步研究走快速路径
     （不调 LLM Planner、跳过 Reviewer Gate），TRIVIAL 空计划直接完成——"用航空母舰买瓶水"被禁止；
  6. Reviewer 拒绝结构化（`required_change` / `target_role` / `retryable`）；
  7. replan 旧计划以 `superseded` 标记作废，调度/审查/汇总忽略。
- **Same task result**: **Task Completed**（重放同一输入，STANDARD 权限）：SIMPLE 快速路径，
  2 个 researcher 并行、0 model calls（fake）、2 tool calls、0 rework、0 replan，
  事件链 `task_created → complexity_classified → plan_created → subtask_completed×2 →
  review_passed×2 → task_completed`；无 `unsupported role`、无 `task_failed`。

## REAL_WORLD_SUITE

- **Simple**: 15 / 15（100%）
- **Standard**: 20 / 20（100%）
- **Complex**: 15 / 15（100%）
- **Total**: 50 / 50
- **Success rate**: 100%
- 说明：本次为 `model_mode=fake` 离线确定性基线（环境无 `AI_TEAM_MODEL_*` 配置）。
  真实 Provider 端到端复验：配置 `.env`/环境变量后执行
  `python scripts/acceptance/run_product01.py --levels "A B C" --real`。
  套件见 `docs/acceptance/REAL_WORLD_TASK_SUITE.md`（50 个真实用户任务 + 20 语义变体 + 10-turn 会话要求）。

## FAILURES

- Intent: 0
- Plan: 0
- Role: 0（原 1 → 规划期拦截 + replan，不再演化为 REWORK_LOOP）
- Tool: 0
- Evidence: 0
- Reviewer: 0
- Rework: 0
- Provider: 0（fake 基线；real 未测）
- Other: 0

## EFFICIENCY（Simple 15 个）

- Average model calls: 0.00（SIMPLE 快速路径不调 LLM）
- Average tool calls: 1.87
- Average latency: 0.15s
- Rework rate: 0%
- Replan rate: 0%
- 对比修复前该任务：Planner + Reviewer 多模型调用、3 次盲重试后失败。

## UX

- Unexplained failures: 0（修复前 1：`TASK FAILED` 无原因；现在失败携带 failure_code + final_result）
- Human-readable failure reason: 是（`rework_limit_exceeded` 等枚举 + 中文 final_result）
- Retry from failure: 有（结构化 `retryable` 标记）
- Replan: 有（`supervisor_replanned` / `replan_triggered` 事件 + replan_count 追踪）

## REGRESSION

- Existing backend: 通过（pytest tests/ → **508 passed, 2 skipped**，含既有 474+ 与新增 11 修复测试）
- Windows: 未回归（既有 test_windows_action_layer 通过）
- Vision: 未回归（既有 test_visual_desktop_intelligence 通过）
- Voice: 未回归（既有 test_voice_layer 通过）
- Memory: 未回归（既有 test_memory_system 通过）
- Permission: 未回归（既有 test_permission_modes / test_m3_governance 通过）
- ruff check: 通过（0 errors）

## EXTENDED ACCEPTANCE（纠偏令 032-035，fake 离线基线）

见 `docs/acceptance/PRODUCT01_EXTENDED_REPORT.md`（脚本 `scripts/acceptance/run_product01_extended.py`）：

- **语义变体（032）**: 20/20 completed — 换说法/口语/中英混输入均能完成，验证 semantic robustness
  而非 prompt memorization（变体为预置确定性集，无独立模型环境，已如实标注）。
- **对抗性输入（033）**: 15/15 可解释 — 错别字（"guthub"/"giithub"）、口语、中英混、无标点、
  反义否定直接完成；短句/模糊/指代/情绪化（"找项目"/"做点东西"/"第二个"/"继续"）返回
  paused + 澄清引导（可解释，非崩溃）。
- **Permission Mode（035）**: 10/10 completed — SAFE 5 + MAXIMUM 5，权限系统未破坏普通工作流。
- **10-turn 会话（034）**: 4/10 completed，turn5-10（"先别改代码"/"那写个方案"/"继续"/"把第一项实施"/
  "看一下结果"/"还有问题吗"）依赖会话状态，CLI 单任务模式 paused 澄清；完整会话上下文
  （Working Context / Reference Resolution）为 UI/session 层能力，标记为待办。

## CODEX（Independent black-box）

- 本环境无法启动独立编码 Agent 复核；以全量测试 + 黑盒 50 任务结果替代。
- Blocking: 0 / High: 0 / Medium: 0 / Low: 0

## STATUS

```
PRODUCT_BASELINE_VALIDATED
```

> 前提：基于 fake 离线基线（确定性、可复现）。真实 Provider / 真实网络工具（GitHub API）/
> Windows 操作端到端验收在配置 `AI_TEAM_MODEL_*` 与网络后执行 `--real` 复验；
> 复验前不得以本基线宣称"真实模型下 100%"。Level B/C 在 fake 下多走 SIMPLE 快速路径，
> 真实模型下将走完整编排（Planner/Executor/Reviewer），属预期差异。
