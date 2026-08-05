# MCP 只读接入（docs/operations/MCP_READONLY_SETUP.md）

对应总管令 006 十。M3-B 实现。

## 1. 静态注册

MCP Server 必须在本机静态配置中注册（用户任务或 LLM 不能动态添加）：

```text
server_id / transport / command_or_url / allowed_tools / read_only /
timeout_seconds / enabled
```

M3-B 提供进程内 FakeMCPServer（transport=memory）用于适配器与网关测试；
真实 stdio/http 冒烟在 M3-B 标记未配置（006 10.3 允许延后，不伪造成功）。

## 2. 只读强制

- 只有已登记 Server 的已登记工具可注册。
- 风险属性一律重设（SAFE + read_only=True），不信任 MCP Server 自报。
- 工具名/描述含写语义关键词（write/create/delete/send/execute/shell 等）→ 默认拒绝。
- 无法确定只读性质的工具默认拒绝。

## 3. 调用链

全部调用经 Tool Gateway：参数 Schema 校验 → 配额 → 执行 → 结果限长 → 脱敏 →
Evidence 固化 → 审计 → Evidence 引用返回。

## 4. 检查

```bash
ai-team-os tools          # 已注册工具含 mcp_<server>_<tool> 前缀
```
