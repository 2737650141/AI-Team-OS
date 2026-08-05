# Tool Gateway 架构（docs/architecture/TOOL_GATEWAY.md）

对应总管令 006 十一。M3-B 实现。

## 1. 执行流程（13 步）

```text
工具查找 → 角色白名单 → 只读检查 → 风险检查 → 参数 Schema → 路径/URL 安全校验
→ 预算与配额 → 调用 → 结果大小限制 → 脱敏 → Evidence 固化 → 审计 → 返回 Evidence 引用
```

实现于 `ToolGateway._invoke`（app/gateway/tool_gateway.py），全程持锁
（并行 Send 下调用顺序可复现）。模型不得直接接收未经处理的原始 HTTP 响应或文件句柄。

## 2. 组件（006 十一）

- `ToolPolicy`：网关级策略（read_only_only、每子任务调用数、Evidence 数、读取字节）。
- `ToolExecutionContext`：task_id/subtask_id/role/tool_call_budget/max_evidence/max_read_bytes
  （由确定性调度器构造，模型不可伪造）。
- `ToolQuota`：运行时配额记账（调用前预留，超限 blocked 不执行 handler）。
- `ToolResultCache`：幂等键 → 成功结果缓存（004 4.x cached_success_result）。
- `EvidenceWriter`：固化（见 EVIDENCE_SYSTEM.md）。

## 3. ToolSpec 扩展

roles（角色白名单）/ args_schema（参数校验）/ url_validator / path_validator /
max_result_bytes——安全校验在网关层确定性执行，工具 handler 只负责纯读取逻辑。

## 4. 拒绝语义

全部拒绝走 `status="blocked"` + 审计事件（tool_role_denied / tool_args_rejected /
tool_url_rejected / tool_path_rejected / tool_quota_exceeded / tool_evidence_quota /
tool_read_quota），handler 永不执行；错误消息为安全消息（脱敏）。
