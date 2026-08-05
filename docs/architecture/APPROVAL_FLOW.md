# 审批流（007 五）

## 审批等级

| 等级       | 含义                     |
| ---------- | ------------------------ |
| none       | 无需审批（读取/只读）   |
| preview    | 预览后放行（新增文件）   |
| explicit   | 显式批准（修改/删除/命令/commit） |
| forbidden  | 禁止（源项目写入/push/发送/设备） |

## ApprovalRequest（5.2）

`approval_id / task_id / run_id / subtask_id / action_type / tool_name / risk_level /
summary / target_paths / command_argv / diff_ref / estimated_file_changes /
estimated_runtime / requested_at / status`。

**不得包含**：API Key、Authorization、完整环境变量、未脱敏文件内容、隐藏模型推理。

## 决策（5.3）

`approved / rejected / expired / cancelled`。

批准绑定：

```text
approval_id + 操作哈希 + 参数哈希 + 目标文件哈希 + 有效期（默认 3600s）
```

批准后参数变化 → 旧批准立即失效（GT-W04）。已拒绝不可再批准；重复批准幂等。

## LangGraph interrupt（5.4）

```text
生成变更提案 → 创建 ApprovalRequest → Checkpoint → paused/awaiting_approval
→ 用户批准/拒绝（CLI approve/reject 或 API）→ 新进程恢复（resume_task）
→ 再验证操作哈希 → 执行或终止
```

- 恢复值 `ApprovalPayload(approval_id, decision, reason)`，与澄清（ClarificationPayload）
  共用同一 interrupt 机制；暂停状态区分 `pending_clarification_id` 与
  `pending_approval_id`。
- 禁止用 CLI 的简单 `--yes` 绕过审批记录。
- Executor 重放语义：LangGraph 恢复会重放 exec 节点，Executor 复用该子任务最新审批
  请求（用户决定绑定其 approval_id），不产生重复审批。

## CLI / API

```text
ai-team-os approvals <run_id>            ai-team-os approve <run_id> <approval_id>
ai-team-os approval-show <approval_id>   ai-team-os reject <run_id> <approval_id> --reason "..."

GET  /tasks/{run_id}/approvals           GET  /approvals/{approval_id}
POST /approvals/{approval_id}/approve    POST /approvals/{approval_id}/reject
```

Approve/Reject 只提交 approval_id（路径）与可选说明；审批参数不能由客户端修改；
操作哈希不匹配返回 409 冲突；API 仅本机单用户，不监听公网。
