# ADR-0009：Diff 绑定审批（diff-bound approvals）

- 状态：已采纳（007 五/八）
- 日期：M3-C

## 背景

审批若只绑定"操作类型"，批准后执行内容可被篡改（TOCTOU）。必须保证
"用户批准的东西"就是"将要执行的东西"。

## 决策

审批批准绑定：

```text
approval_id + 操作哈希 + 参数哈希 + 目标文件哈希 + 有效期
```

- 操作哈希：action_type + tool_name + summary + target_paths + command_argv + diff_ref。
- 参数哈希：实际执行参数（如 patch_json）的稳定哈希。
- 目标哈希：目标文件当前内容哈希。
- 执行前再验证（verify_execution）：任一不匹配 → 确定性拒绝，不写文件（GT-W04）。
- 用户必须先看到 Diff（diff Artifact）才能批准；Diff 引用记入 diff_ref。

## 后果

- 审批流与 LangGraph interrupt 集成：提案 → Checkpoint → 暂停 → 决策 → 恢复 → 再验证。
- 重放语义：Executor 复用该子任务最新审批请求，避免重复审批。
- 参数或文件在批准后被修改，旧批准立即失效。
