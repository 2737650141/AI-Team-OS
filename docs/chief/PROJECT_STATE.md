# PROJECT_STATE

> 项目状态快照（供全新 Codex 会话恢复上下文用）。不含执行日记；
> 工作规则见 `docs/chief/CODEX_PROTOCOL.md`。

## 当前架构

- **语言/运行时**：Python ≥3.11（后端）+ Rust/Tauri 2（桌面壳）+ TypeScript/React/Vite（Web UI，`web/`）+ NSIS 安装包。
- **核心编排**：LangGraph 多智能体图（`app/graph.py`）：
  `ingest → clarify → plan(Supervisor/Planner) → dispatch → exec_subtask(Executor/Researcher) → review_all(Reviewer) → finalize`；
  失败/返工路径：`review_all → plan`（Supervisor replan，`REPLAN_LIMIT=2`）、`fail_rework_limit`。
- **确定性内核**：`app/gateway/tool_gateway.py` 唯一工具执行入口（参数 schema 白名单过滤 + audit）；
  `app/core/budget.py` BudgetController（预算冻结 + 唯一记账）；`app/core/events.py` 事件审计。
- **角色**（`app/core/registry.py`，5 角色全 enabled）：supervisor / planner / researcher / executor / reviewer；
  运行时**可执行**角色仅 `executor`、`researcher`（`plan_validator.EXECUTABLE_ROLES`）。
- **复杂度分类**：`app/core/complexity.py` TaskComplexityClassifier（TRIVIAL/SIMPLE/STANDARD/COMPLEX）；
  SIMPLE 走确定性快速路径（2 个并行 researcher、不调 LLM planner、reviewer gate 可跳过）。
- **真实 Provider**：`app/runner.py::build_provider` → `_default_custom_provider` → SecretResolver
  （`app/core/secret_store.py`：Session → Windows Secure Store(DPAPI) → Env → Missing）。
  当前默认 **DeepSeek Official**（`api.deepseek.com`，`deepseek-v4-flash`）。
- **会话/上下文**：`app/conversation/` ConversationSession（Working Context，非长期记忆：current_goal/
  recent_turns/selected_item/pending_plan/current_task_reference/no_write）+ ConversationReferenceResolver
  （第二个/继续/第一项/刚才那个，优先级 Current Turn > Working Context > Current Task > Memory）。
- **权限**：`app/security/permissions.py` PermissionStore（SAFE/STANDARD/MAXIMUM，持久化）。
- **观测**：`app/usage/store.py` token/cost 归属（REPORTED/ESTIMATED/UNAVAILABLE）；桌面 Usage 页。
- **验收运行时**：`app/acceptance_runtime.py`（Acceptance Runtime = Production Runtime，
  无凭据 → `WAITING_FOR_USER_CREDENTIAL_INPUT`，不降级 Fake）。

## 已完成阶段

- **M6-P**（治理运行时）：多智能体编排、预算冻结、权限模式、事件审计、rework guard、Supervisor replan、
  复杂度分类、真实 Provider 集成（020 系列）。
- **M6-P2 Developer Preview 0.1.0**（桌面发布）：Tauri 壳（单实例/托盘/close-to-tray/sidecar 生命周期）、
  PyInstaller windowed 后端（loopback 动态端口 + per-launch token）、NSIS per-user 安装、Usage observatory、
  权限持久化、升级安装保留数据。发布证据 `docs/acceptance/M6P2_ACCEPTANCE_REPORT.md`。
- **UX-03 JARVIS interaction workspace**（本轮 checkpoint）：`app/core/interaction_settings.py` +
  `app/core/task_control.py` + `web/src/pages/Jarvis.tsx` / `JarvisNotifications.tsx` / Usage 页；
  后端 25 测试 + 前端 22 测试全绿。
- **PRODUCT-01 / PRODUCT-02 真实门禁**：见"关键真实门禁"。

## 冻结能力（已验收，不得回退）

- M6-P2 桌面发布能力：单实例、托盘、关闭到托盘、优雅退出、pause JARVIS/stop Computer Control/
  Voice on-off、动态端口 + 会话 token、升级保留配置/DPAPI 密钥/权限/用量历史。
- Usage observatory：REPORTED/ESTIMATED/UNAVAILABLE 标记、Diagnostic 分离、SQLite 持久化、
  隐私 schema（不含 prompt/response/secret/API key/COT）。
- UX-03 Jarvis 交互工作区（commit `6d3f1cb`）：交互设置 + 任务控制 + 通知 + Usage 页。
- 权限模式持久化；SecretResolver → Windows Secure Store 凭据链路；验收脚本不降级 Fake。
- 工具网关参数白名单过滤（LLM 幻觉参数不崩溃）；`github_search_repositories` sort/order。

## 当前分支 / HEAD

- 分支：`phase-6p2/desktop-usage-observatory`
- HEAD：`6d3f1cb`（feat: add jarvis interaction workspace），父 `d892fe3`
  （docs: record final M6-P2 release evidence）
- 工作区：干净（checkpoint 已提交）

## 关键真实门禁

- **PRODUCT-01（020-B）真实重放**：PASS——原失败任务（GitHub 热门项目）真实 DeepSeek 重放，
  REAL_MODEL=TRUE、FAKE_CALLS=0、真实 GitHub API 数据、COMPLETED、0 rework。
- **REAL SIMPLE**：10/10 PASS（真实模型 + 真实 GitHub 工具，平均 ~7.6 calls / ~$0.001 / 0 rework）。
- **REAL STANDARD**：0/10 FAIL → **PRODUCT_BASELINE_PARTIAL**（见已知问题 #1）。
- **REAL COMPLEX**：未测（同 STANDARD 根因，避免烧费）。
- **10-turn 会话**：fake 确定性层 10/10 PASS（之前 4/10 已修复）；真实模型复验未做。
- **PRODUCT-02 Core Benchmark**：9/9 PASS（3 轮 × read_only_research/code_change/code_analysis，
  DeepSeek 真实调用，0 rework，平均 5.22 calls）。
- **M6-P2 安装验收**：本机安装/升级/托盘/用量页全过；**CLEAN_INSTALL 未验证**
  （Windows Sandbox/VM 不可用）→ M6-P 未宣告 complete。

## 当前已知问题

1. **STANDARD/COMPLEX 完整编排真实不稳定**（阻塞 PRODUCT-01 全绿）：
   - LLM planner bounded repair 轮次多、预算膨胀（观测到 81 calls / 94k tokens 仍 budget_exceeded）；
   - 真实 reviewer 按 acceptance_criteria 严格拒绝（缺 license/stars 等字段）→ rework 循环；
   - researcher 真实 GitHub 数据获取不稳定（工具参数缺失/幻觉）。
   - 已缓解：tool 参数 schema 注入（`describe_tools`）、rework 上限 → Supervisor replan 兜底、
     failure_code 映射（provider_error/budget_exceeded 不崩溃）。根治需下阶段。
2. **CLEAN_INSTALL NOT VALIDATED**：需干净 Windows（无 Python/Node/源码）环境验证最终安装包。
3. **真实模型 10-turn 复验未做**：ConversationSession 为确定性层，fake/real 行为一致但未跑真实调用。
4. 低风险遗留：并行 Send 写 `replan_reason` 竞态（仅影响日志）；superseded 旧 subtask 的 pending
   approval 残留（real 审批流相关）；langgraph 反序列化未注册类型警告（未来版本会变 error）。
5. **UX-03 收口 review（2026-08-14）should-fix**：`app/api/server.py:346` `_steering_kind` 的
   CHANGE_SCOPE 正则过宽（"不要/别/仅/范围"任意命中）——"不要继续查了"类停止意图会走
   add_constraint 而非 stop 邮箱；建议把停止类短语并入 STOP/PAUSE 精确集合（下阶段 024 处理）。
   nits：RESUME 分支 `resume_task` 未捕获 RuntimeError（建议 409）；`_voice_supervisor` 改用统一
   "jarvis-desktop" 会话需产品确认。

## Deferred（下阶段候选）

- planner 预算分配优化（避免 bounded repair 膨胀 / 完整编排成本失控）。
- reviewer 真实模式门槛校准（区分"关键失败"与"信息缺失可标注 unverified"）。
- researcher 工具失败自愈（按 `describe_tools` 参数重试）。
- 真实模型 10-turn 复验 + REAL COMPLEX 产品集（待 #1 缓解后，受 `max_real_requests` 费用上限约束）。
- CLEAN_INSTALL（需外部干净 Windows 环境）。

## 下一阶段 024

- 总管令 024 尚未下发；PROJECT_STATE 收口时（2026-08-14）的待办方向：
  - 依据本文件"已知问题 #1 / Deferred"稳定 STANDARD/COMPLEX 真实编排（这是 PRODUCT_BASELINE_VALIDATED 的前提）；
  - 或按 024 具体指令执行（以总管令为准）。
