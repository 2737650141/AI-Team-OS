# ADR-0006：先只读工具、后写工具（006 二十）

- 状态：已接受（M3-B）
- 日期：2026-08-05
- 关联：docs/security/READONLY_TOOL_SECURITY.md

## 背景

M3-B 目标是把真实只读取证安全放入确定性状态机；写能力（文件修改/Shell/网络副作用）
风险远高于只读，且本阶段尚无审批流（M2 的审批流在 M3 实现）。

## 决策

本阶段只实现只读工具（GitHub 仅 GET、web_fetch GET、本地文件只读、MCP 只读适配层），
全部 risk_level=safe / read_only=true / requires_approval=false，且 Tool Gateway
确定性拦截任何非只读工具（handler 永不执行）。

不得实现（M3-C 之前）：Executor 写文件、Patch 应用、Shell 命令、Git commit、
依赖安装、PR、删除、邮件、设备操作。

## 影响

- 好处：真实任务零副作用风险；写工具的审批/配额设计可在 M3-C 单独评审。
- 代价：本阶段不能执行写型真实任务（用户要求的边界内）。
