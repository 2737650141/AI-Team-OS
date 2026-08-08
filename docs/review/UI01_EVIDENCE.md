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

- 普通 review（sa_20260808_120531，2 轮）：第 1 轮 3 blocking（SSE 命名事件不达
  客户端、sync generator 热循环、replay 未实现）+ 3 should-fix（resolver env
  别名、subtask 字段映射、Setup 先保存）+ nits；第 2 轮发现 SSE 终态重连循环
  should-fix → 全部修复（4538b7a / f021041：默认 message 帧、time.sleep 节流、
  ?after= replay、终态完整形状 + 客户端 es.close()）。复查 verdict=pass。
- security_review（sa_20260808_122950，2 轮）：无 HIGH/MEDIUM；4 LOW 全部处理
  ——zip 名称级排除（.env*/*.pem/*.key/…）、loopback bind guard（__main__ 拒绝
  非回环 host）、已知 LOW 记录（DNS-rebinding TOCTOU、SSE 每流占用线程池线程）。
  复查 verdict=pass。

## 十二、已知限制

- 单用户本地环境；无公网部署/多用户。
- WindowsSecretStore 仅 Windows（DPAPI）；其他平台需实现对应后端。
- 真实 Provider 健康检查在无凭据时不可测（Test Connection 显示状态映射）。
- M4 Memory 仅占位；未实现长期保存。
- E2E 覆盖 demo 主流程；更多场景（rework/UI-07 reject 文件不变）由 component/API 测试覆盖。
- SSE sync generator 每连接占用一个线程池线程（任务终态自动关闭）；并发连接数高时
  需改 async 实现（已知 LOW）。
- test_connection 存在 DNS-rebinding TOCTOU（校验与连接分离解析），本地单用户场景
  风险可接受（已知 LOW）。

## 十三、最终验证

- pytest：321 passed + 2 skipped（最后提交 b7b3f3c 后）。
- ruff check/format --check（app tests scripts）：全绿 94 文件。
- mypy app：55 source files no issues。
- Frontend：typecheck ✓ / lint ✓ / Vitest 4 passed / build ✓（dist 241KB / gzip 75KB）。
- E2E：Playwright 1 passed（demo lifecycle：创建→Approval→Approve→Completed→刷新恢复；
  前置：后端带 AI_TEAM_ALLOWED_READ_ROOTS=fixtures，见 DEMO_MODE.md）。
- git status 干净；无 remote；未 push；git diff --check 通过。
- 证据包：artifacts/review/ui01-source.zip（敏感扫描 clean）。
- 截图：artifacts/demo/ui/ 9 张（E2E 复跑后刷新）。

## 十四、交付检查补漏（010 六十五）

- UI-01 已普通 merge 回 main（a990464 --no-ff，55 files +9110/-5，无冲突；
  后续 b7b3f3c 文档补漏）。phase-ui/web-control-center 分支保留。
- 启动依赖审计：start_ai_team_os.ps1 自动设置 AI_TEAM_ALLOWED_READ_ROOTS=fixtures；
  文档补齐 E2E 前置条件（缺省时沙箱任务 500）。
- .gitignore 补 web/.vite/（vite 缓存）。
- 交付检查全部通过：SEC-01 CLOSED、组件清单完整、测试/双审/证据包/截图/文档
  齐全、main 为完整交付基线、无 remote 未 push、不进入 M4（Memory 占位）。

## 十五、010-B 用户实机验收（UI-01 延续）

- i18n（010-B 九）：中/英双语言，默认中文，localStorage（aios.lang）记忆；
  全界面同步切换（导航/菜单/按钮/状态徽章/提示/错误/Approval/Diff/Plan/Tests/
  Reviewer/Settings/Setup/Logs/Tools/Evidence/Memory）；右上角切换器。
  提交 20acaa7。
- Demo 入口（010-B 五）：Dashboard Try Demo Mode 一键按钮（sandbox_code_fix）。
- 一键启动（010-B 三）：start_ai_team_os.ps1 补齐 Python 检查/健康等待/失败提示/
  自动开浏览器；npm 启动改 cmd /c 包装（Start-Process 直启 npm 静默失败）；
  ReadKey 非交互保护（85ae53c）。桌面入口 Start AI Team OS.cmd（010-B 十三）。
- 验收 E2E（e2e/ui010b*.spec.ts）：首页中文默认 + Try Demo + 中英切换 +
  Settings 安全显示（无 sk-/reasonix/.create_token）；Demo 任务
  （run 496187744ea64471）审批页就绪（批准/拒绝/Diff 可见），未自动 Approve，
  等待用户本人操作（010-B 六）。
- 截图：artifacts/demo/ui/ 12 张（含 ui010b-home-zh/home-en/settings/approval）。
- 刷新恢复（010-B 十一）与后端重启恢复（010-B 十二）由既有 E2E/测试覆盖。
- 服务验证：backend 8000 / frontend 5173 / proxy /api 全 200；ps1 完整实际运行
  [OK] Backend + [OK] Frontend。全量 pytest 321 passed。
