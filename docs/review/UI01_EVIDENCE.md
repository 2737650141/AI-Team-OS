# UI-01 Evidence（总管令 010：Web Control Center + 网页安全密钥管理）

阶段：UI-01（Web Control Center / M3-D）
分支：phase-ui/web-control-center（自 main 06ecb56 创建）
提交：d218429（EventStore/SSE/API）→ 64b8f96（SecretStore/Connections）→
fce9bab（前端全量）→ e5c026e（清理）→（文档/证据 追加）

## 一、SECURITY_GATE

- Rotation confirmation：`AI_TEAM_SECRET_ROTATION_CONFIRMED=true`（010 1.1 实测）
- SEC-01：**CLOSED**（CLOSED_BY_USER_ROTATION_CONFIRMATION，010 1.3；
  docs/security/SECURITY_INCIDENT_001.md §9 更新）
- Git history：`git log --all -- reasonix.toml` 空；泄漏 blob 7f5ddf95 已删
- Reflog：无泄漏引用
- Secret scan：pre-commit + 打包共享 `SECRET_PATTERNS`；`m3c-source-clean.zip` clean

## 二、WEB

- Frontend：React 18 + TS + Vite（web/）；Backend：FastAPI
- URL：http://127.0.0.1:5173（前端）/ http://127.0.0.1:8000（API，127.0.0.1 only）
- Start：`scripts/start_ai_team_os.ps1` 一键启动；或 uvicorn + `npm run dev`
- Demo Mode：无 Key 完整流程（E2E 验证）

## 三、PAGES

Dashboard（Health/Metrics/New Task/Recent/Agent Team）、Tasks、Task Detail
（Header/Timeline/Plan/Activity/Approval/Diff/Tests/Reviewer/Evidence）、
Agents（只读）、Approvals（导航）、Evidence、Tools、Logs（SSE tail）、
Settings+Connections、Memory 占位、Setup 向导。

## 四、REALTIME

- EventStore：SQLite（runtime/events.sqlite）、sequence 单调、run_id 查询、replay
- SSE：GET /tasks/{run_id}/events + keepalive + Last-Event-ID + 断线重连
- Refresh recovery：刷新后从 API 全量恢复
- Restart recovery：checkpoints.db + events.sqlite 跨进程持久

## 五、TASK_VISUALIZATION

Workflow Timeline（9 阶段颜色）、Plan 面板（subtask/role/deps/status/rework）、
Agent 状态徽章、工具事件（tool_started/completed/blocked）、Evidence 行、
Reviewer/Rework 显示。

## 六、APPROVAL

ApprovalCard（Agent/Action/Risk/Files/Summary/Diff 引用）+ Approve/Reject(Reason)；
Approve 后沙箱应用补丁 → 白名单 pytest → Reviewer。

## 七、SECRET_MANAGEMENT

- SecretStore：SessionSecretStore + WindowsSecretStore（DPAPI）
- SecretResolver：Session → Secure → ENV → Missing
- Connections API：GET（无 Secret）/ PUT（session|secure，不回显）/ DELETE / test
  （安全映射）；Ollama local_provider 放行 localhost
- Browser：type=password、提交后清空、无任何持久化
- Audit/Event/Evidence 脱敏测试

## 八、DEMO

`sandbox_code_fix` + `sample-python`：创建→Planner→Evidence→Approval→Approve→
Tests→Reviewer→Completed；Cost=$0；E2E 自动验证含刷新恢复。

## 九、测试

- Backend：pytest 317 passed + 2 skipped（含 test_ui_events 6 + test_secret_connections 9）
- Frontend：typecheck ✓ / lint ✓ / Vitest 4 passed / build ✓
- E2E：Playwright 1 passed（demo lifecycle 全流程 + 截图）
- 默认真实网络请求：0（全部 MockTransport/IP 字面量；test_connection 无凭据早返回）

## 十、截图

artifacts/demo/ui/：dashboard / task-detail / approval / completed / agents /
tools / evidence / settings / memory（9 张，无 Secret/真实敏感文件）

## 十一、双重审查

（最终验证后填写：普通 review + security review 结论）

## 十二、已知限制

- 单用户本地环境；无公网部署/多用户。
- WindowsSecretStore 仅 Windows（DPAPI）；其他平台需实现对应后端。
- 真实 Provider 健康检查在无凭据时不可测（Test Connection 显示状态映射）。
- M4 Memory 仅占位；未实现长期保存。
- E2E 覆盖 demo 主流程；更多场景（rework/UI-07 reject 文件不变）由 component/API 测试覆盖。

## 十三、最终验证

（封板时填写：pytest/ruff/mypy + typecheck/lint/test/build + git status/remote）
