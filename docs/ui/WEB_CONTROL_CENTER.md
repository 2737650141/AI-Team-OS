# Web Control Center（010 四~四十七）

## 产品

**AI Team OS · Control Center**：本地桌面级 Web 控制台，让用户无需阅读原始日志即可
查看与操作整个 Agent 团队。

入口：`http://127.0.0.1:5173`（仅本机监听）。

## 技术栈（010 四，冻结）

- Frontend：React 18 + TypeScript + Vite + React Router + TanStack Query + Lucide
- Backend：现有 FastAPI（不引入第二后端框架）
- Realtime：Server-Sent Events（第一版不用 WebSocket）
- Orchestration：LangGraph（唯一编排核心）

## 目录

```
web/
├─ src/
│  ├─ api/        API 客户端 + 类型（/api 代理到 FastAPI）
│  ├─ components/ StatusBadge / Timeline / PlanPanel / ActivityFeed /
│  │              ApprovalCard / DiffViewer
│  ├─ hooks/      useEvents（SSE）
│  ├─ layouts/    AppLayout（Sidebar）
│  ├─ pages/      Dashboard / Tasks / TaskDetail / Agents / Evidence /
│  │              Tools / Logs / Memory / Settings / Setup
│  ├─ App.tsx     路由
│  └─ main.tsx
├─ e2e/           Playwright E2E（demo lifecycle）
├─ package.json / tsconfig.json / vite.config.ts / eslint.config.js
└─ playwright.config.ts
```

## 页面

| 路径 | 内容（010 章节） |
| ---- | ---------------- |
| `/` | Dashboard：System Health + Metrics + New Task + Recent Tasks + Agent Team（七/八） |
| `/tasks` | 任务列表（九） |
| `/tasks/:runId` | Task Detail：Header / Workflow Timeline / Plan / Activity Feed(SSE) / Approval / Diff / Tests / Reviewer / Evidence（九~二十一） |
| `/approvals` | 导航到最新任务的审批（十六） |
| `/agents` | Agent 目录（只读）（二十二） |
| `/evidence` | Evidence 列表（二十一） |
| `/tools` | 工具目录（二十三） |
| `/logs` | 结构化事件流（SSE tail + 过滤）（二十四） |
| `/memory` | 占位（四十） |
| `/settings` | System Status + Connections（二十五/三十~三十六） |
| `/setup` | 首配向导（三十七） |

## 实时（010 二十四/二十五/二十六）

- 后端 `EventStore`（SQLite 持久化、sequence 单调、run_id 查询、replay）。
- `GET /tasks/{run_id}/events`：SSE，支持 `Last-Event-ID` 恢复；断线自动重连。
- 浏览器刷新后全部状态从 API 恢复（React 内存不是唯一来源）。

## 启动（010 四十六/四十七）

```bash
# 终端 1
python -m uvicorn app.api.server:app --host 127.0.0.1 --port 8000
# 终端 2
cd web && npm run dev -- --host 127.0.0.1
# 或一键
powershell -ExecutionPolicy Bypass -File scripts/start_ai_team_os.ps1
```

前端 `/api` 代理到 `http://127.0.0.1:8000`。**默认不监听 0.0.0.0。**

## Demo Mode（010 三十二/三十八）

无任何 API Key 即可完整体验：Fake Model + Fixture GitHub + Sandbox 示例项目 +
Fake Approval Flow（输入任务 → Plan → Research → Evidence → Executor → Diff →
Approval → Tests → Reviewer → Completed）。

官方 Demo 任务：`sandbox_code_fix`（修复 fixtures/sample-python 的失败测试，
项目别名 `sample-python`）。
