# ADR-0005：Evidence-first 工具结果（006 五）

- 状态：已接受（M3-B）
- 日期：2026-08-05
- 关联：docs/architecture/EVIDENCE_SYSTEM.md、docs/architecture/TOOL_GATEWAY.md

## 背景

真实工具（GitHub/网页/本地文件/MCP）结果若直接交给模型，会造成：
结论与来源脱钩（Reviewer 无法核查）、内容重复存储、凭据泄漏面扩大。

## 决策

所有真实工具结果必须先固化为统一 Evidence（EvidenceRecord，14 字段 + 快照），
再交给模型；Claim 只引用 Evidence ID；Reviewer 可经 ID 定位原始快照。

- 快照目录 runtime/evidence/<task_id>/（Git 忽略，统一脱敏落盘）。
- 哈希去重：同一内容不重复存储；截断必须显式标记 truncated=true。
- 固化时机在 Tool Gateway 执行流程第 11 步（调用成功后、返回前）。

## 影响

- 好处：可核查性（来源/时间/哈希）、去重省空间、凭据过滤集中、审计完整。
- 代价：每条工具结果多一次快照写入与哈希计算（可忽略）。
