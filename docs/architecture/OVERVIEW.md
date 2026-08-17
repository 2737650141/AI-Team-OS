# AI Team OS — Architecture Overview

> Public-facing overview of the implemented system. Design decisions are recorded in
> [docs/adr](../adr/); milestone-specific deep dives live in this directory.

## Design principles

- **Thin frontend, governed core** — the web UI is a control surface; all business logic,
  security, and budget enforcement live in the Python core.
- **Two chokepoints** — every model call goes through the **Model Gateway** (single budget/audit
  ledger) and every tool call through the **Tool Gateway** (authn → budget → approval → execute →
  evidence).
- **Deterministic security** — permission modes, approval gates, budgets, and sandbox boundaries
  are enforced by deterministic code. The LLM never owns a security decision.
- **Local-first** — loopback-only API, per-launch session token, on-device SQLite, no telemetry,
  no cloud dependency.

## System components

```mermaid
flowchart TB
    subgraph SHELL["Desktop Shell (Tauri 2, Windows)"]
        TRAY["Tray / single-instance / close-to-tray"]
        WEBVIEW["WebView — Control Center<br/>(React + Vite + TypeScript, 中/EN)"]
    end

    subgraph SIDECAR["Python Sidecar (PyInstaller, loopback-only)"]
        API["FastAPI<br/>REST + SSE"]
        ORCH["LangGraph Orchestration<br/>Supervisor · Planner · Researcher<br/>Executor · Reviewer"]
        MG["Model Gateway<br/>role routing · multi-provider adapters<br/>budget ledger · audit"]
        TG["Tool Gateway<br/>ToolSpec · MCP · read-only policy<br/>risk levels · approval"]
        SEC["Security Core<br/>permission modes · secret store<br/>sandbox workspace"]
        MEM["Memory Service<br/>SQLite FTS · proposals · retrieval"]
        USAGE["Usage Observatory<br/>token / cost / context telemetry"]
        VOICE["JARVIS Voice<br/>VAD · wake word · Whisper · SAPI TTS"]
        VISION["Desktop Vision<br/>mss capture · OpenCV · UIA"]
    end

    subgraph DATA["Local Data (per-user AppData)"]
        DB[("SQLite<br/>checkpoint · memory · usage · settings")]
        SECRETS[("Encrypted secret store")]
        FS["artifacts / evidence / workspaces"]
    end

    TRAY --> WEBVIEW
    WEBVIEW -->|"REST + SSE, session token"| API
    API --> ORCH
    ORCH --> MG
    ORCH --> TG
    ORCH --> MEM
    ORCH --> USAGE
    TG --> SEC
    VOICE --> ORCH
    VISION --> TG
    ORCH --> DB
    MEM --> DB
    USAGE --> DB
    SEC --> SECRETS
    TG --> FS
    ORCH --> FS
```

## Task lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant UI as Control Center
    participant API as FastAPI
    participant G as LangGraph
    participant S as Supervisor
    participant P as Planner
    participant R as Researcher/Executor
    participant V as Reviewer
    participant TG as Tool Gateway
    participant MEM as Memory

    U->>UI: 提出目标（一句话）
    UI->>API: POST /tasks
    API->>G: 启动任务实例（checkpoint 持久化）
    G->>S: ingest
    S->>MEM: 检索项目记忆与用户偏好
    alt 目标模糊
        S->>U: 澄清问题（interrupt）
        U->>S: 回答
    end
    S->>P: 生成结构化计划
    P->>S: 子任务 + 依赖 + 预算分配
    loop 每个子任务
        S->>R: 派发（按 Agent Registry）
        R->>TG: 只读/写工具调用
        TG->>U: 高风险操作审批（interrupt）
        U->>TG: 批准 / 拒绝
        R->>V: 产物 + 证据（不含中间推理）
        V->>S: pass / reject（定向修改意见）
        S->>R: 驳回 → 定向返工（预算内）
    end
    S->>UI: 最终结果 + 证据链 + 用量报告
    S->>MEM: 记忆提案（确定性过滤）
    MEM->>U: 确认后写入长期记忆
```

## Agent roles

| Role | Responsibility | Key constraints |
| --- | --- | --- |
| Supervisor | 持有"当前该做什么"决策：选 agent、派发、处理失败/驳回 | 不执行具体工作；硬步数上限；禁止 agent 互调 |
| Planner | 目标 → 结构化计划（子任务、依赖、预算分配） | 输出经 schema/无环/预算校验 |
| Researcher | 只读调研：GitHub、Web、本地文件、MCP 证据采集 | 只读工具；证据落盘 |
| Executor | 实施动作：读写沙箱工作区、补丁、跑测试 | 写操作限沙箱；危险操作硬拦截 |
| Reviewer | 独立审查：确定性校验 + LLM 评审 | 只读角色；不接收 Executor 中间推理 |

## Permission modes

| Mode | Behavior |
| --- | --- |
| **Safe（安全）** | 只读与真正低风险操作自动执行；写入、测试、电脑状态变化需询问 |
| **Standard（标准，默认）** | 普通开发/调研自动完成；删除、外部发送、系统修改、敏感行为需询问 |
| **Maximum（最高权限）** | 目标内大多数操作自动执行；密码、Secret、UAC、核心安全系统与 STOP 不可绕过 |

模式持久化保存，跨任务生效；所有高风险审批记录审计日志。

## Voice (JARVIS) and desktop control

- **Voice path**: `sounddevice/WASAPI → 16 kHz bounded queue → Silero VAD → openWakeWord (optional) / push-to-talk → Whisper (local) → transcript → Supervisor`. Raw audio never persists.
- **Deterministic intents**: `STOP / Cancel / Pause / Reject` 是精确本地匹配，不经过 LLM；语音不用于审批高风险操作。
- **Desktop control**: Windows UIA 可访问性树 + mss 多显示器截图 + OpenCV 确定性视觉定位（模板/颜色/轮廓），全部经 Tool Gateway 权限与审批收口。

## Data & privacy

- 所有状态在本机：SQLite（checkpoint、记忆、用量、设置）+ 加密 Secret Store（凭据）+ 文件系统（产物/证据/沙箱工作区）。
- API 仅监听 `127.0.0.1`，每次启动生成随机 48 字符会话令牌，无固定端口/令牌。
- 无遥测、无云依赖；真实模型由用户自行配置 Provider（OpenAI 兼容端点、DeepSeek、Ollama 等）。
