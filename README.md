# AI Team OS

AI 智能体协作团队平台（MVP）。让用户提出目标，系统自动完成意图理解、计划、多智能体执行、审查与返工。

当前状态：**M6-P Desktop Productization**。现已包含多 Provider Agent Team、JARVIS 本地语音与视觉、受治理长期记忆，以及持久化 Safe / Standard / Maximum 三档权限模式。

规划文档见 `docs/planning/`（Phase 0 已通过；M0-00 校准已完成）。

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/ai-team-os run "你好，请介绍一下你自己" --budget-tokens 5000
```

## 测试

```bash
.venv/Scripts/pytest
```

## 目录结构

- `app/core/` — 状态模型、预算
- `app/memory/` — 记忆策略、SQLite/FTS、检索与上下文治理
- `app/gateway/` — Model Gateway / Tool Gateway
- `app/tools/` — ToolSpec 与工具
- `app/api/` — 最小 FastAPI
- `tests/` — pytest（权限拦截、硬预算、恢复）
- `web/` — 双语 Control Center、Memory Center 与 Connections

记忆架构与操作说明见 `docs/architecture/MEMORY_SYSTEM.md` 和 `docs/operations/MEMORY_MANAGEMENT.md`。
