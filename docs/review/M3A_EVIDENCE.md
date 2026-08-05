# M3-A 证据（docs/review/M3A_EVIDENCE.md）

阶段：M3-A 真实模型网关、角色模型路由与生产级输出治理（总管令 005）
分支：phase-3a/real-model-gateway（自 main 430c5d6 创建）
提交：97830ad → 772a309（7 个提交，见 artifacts/review/m3a-git-log.txt）

## 1. M2 限制修复（004 4.x）

- 幂等命中返回 `cached_success_result`（原 Evidence ID / 结构化结果 / 原始执行时间 / 内容哈希），
  handler 不重复执行；参数变化产生新幂等键与真实调用。
- 工具型子任务驳回后返工：缓存命中 → 非空产物 → Reviewer 通过（端到端场景
  `scenario:reject-tool-once`）；旧审查历史保留；全程经 Tool Gateway。
- 新增 8 项测试（tests/test_m3_rework_cache.py，4.3 第 1-8 条全覆盖）。

## 2. 配置与 Provider

- AppSettings/ModelProviderSettings/ModelRouteSettings（Pydantic Settings），
  11 个 `AI_TEAM_MODEL_*` 环境变量；API Key 只从环境变量读取（env_file=None 显式禁用）。
- ModelProvider 契约：ModelRequest（无 Key）/ModelResponse/ProviderError（13 分类）/
  ProviderHealth/UsageEstimate；FakeModelProvider 为测试基线（保留 chat 兼容）。
- OpenAICompatibleProvider：Chat Completions 第一版协议（ADR-0003）；
  httpx 显式超时/连接复用/不自动重定向/UA；Base URL SSRF 校验（仅 https、拒环回/
  RFC1918/链路本地/云元数据/域名解析复查/重定向复查/解析失败拒绝）；响应体 1MB 限制；
  `AI_TEAM_MODEL_ENABLE_REAL=true` 才允许真实调用。

## 3. 路由 / 输出治理 / 预算 / 重试

- ModelRouter：5 角色默认策略 + 任务级覆盖白名单（审计）+ fallback 确定性降级（审计）。
- 结构化输出：提取（单顶层对象/拒多对象/拒超大/拒 Schema 外字段）→ Pydantic 校验 →
  修复循环（上限集中配置，超限 SCHEMA_VALIDATION_FAILED 不写状态）。
- 预算：调用前预留（estimated/reserved）→ 预算不足不调用（BUDGET_INSUFFICIENT）→
  实际结算（价格表集中配置，未知价格 estimated_cost=None 不伪造）；恢复不清零。
- 重试：可重试分类、指数退避（0.5→8s）、每尝试审计、重试不重置预算、sleep_fn 注入
  （自动测试零真实 sleep）；usage 缺失按估算记账（防预算绕过）。

## 4. 角色实现与 Prompt

- LLMPlanner（Plan Schema → 10 项确定性校验）/ LLMResearcher（只读 Fixture Tool，
  模型解释证据）/ LLMReviewer（确定性失败直接 reject 不调模型）/ LLMSupervisorDecision
  （仅语言组织，失败回退确定性汇总）；Fake 版本保留（model_mode 选择）。
- app/prompts/ 注册表：prompt_id/version/hash/forbidden_actions；
  UNTRUSTED_EXTERNAL_CONTENT 注入边界；审计记录 prompt 版本与哈希。
- ContextBuilder：四角色上下文契约 + 裁剪（context_truncated）。

## 5. CLI/API

- CLI：`providers` / `provider-health` / `run --model-mode` / `--dry-run` / `--model-override`。
- API：GET /providers、/providers/health、POST /tasks（model_mode 默认 fake、
  model_overrides 白名单）、/tasks/{id}/dry-run；客户端不能传 base_url/API Key；
  非法覆盖 → 400；API 预算上限（token ≤ 1M、cost ≤ 100）；本地单用户模式。

## 6. 测试结果

- pytest：**113 passed**（61 M1/M2 回归 + 52 M3-A 新增），仅 StarletteDeprecationWarning。
- Ruff format --check：49 files already formatted；Ruff check：All checks passed。
- mypy app：34 source files no issues。
- Mock HTTP 12 项：httpx MockTransport，零真实网络、零真实 DNS
  （base_url 用公网 IP 字面量 8.8.8.8）。
- 默认网络请求次数：0（全部自动测试离线，无网络导入静态检查通过）。

## 7. 真实模型手动测试

- 环境无 `AI_TEAM_MODEL_ENABLE_REAL=true` 与 API Key（005 十九）。
- 自动测试与 Mock HTTP 照常完成；真实测试标记 **BLOCKED_BY_CREDENTIALS**。
- 证据：`ai-team-os run github_compare_team --model-mode real` → 确定性 CONFIG_ERROR
  "real model calls disabled"（不会静默调用）；`provider-health` → disabled。
- 真实 Provider 代码已就绪（AI_TEAM_MODEL_ENABLE_REAL=true + API Key 后可立即手动实测，
  流程见 docs/operations/REAL_MODEL_SETUP.md）。

## 8. 双重审查

- 普通 review（sa_20260805_030111... 三轮 continue_from）：最终 verdict=pass。
  修复项：成本价格表、响应体限制、overrides 生效、max_retries 配置传递、
  usage 缺失估算、DNS 解析失败拒绝、API 预算上限、回灌截断、ValueError→400、
  BudgetExceeded 真实 used 值；全部有回归测试。
- Security review（sa_20260805_025749... 两轮 continue_from）：最终 verdict=pass。
  修复项：DNS 解析失败拒绝（TOCTOU 解析侧）、API 预算上限、usage 估算记账、
  回灌截断 500 字符、mock 零 DNS；无 CRITICAL/HIGH。
- 遗留 LOW（不阻塞，后续处理）：ModelGateway.budget property 暴露可变 BudgetController
  （威胁面仅服务端可信代码，模型无法利用；建议后续改只读视图）。

## 9. 限制与后续阶段

- 真实 Provider 实测受凭据阻塞（BLOCKED_BY_CREDENTIALS）；Mock HTTP 与 Fake 全绿。
- 响应体限制为接收后检查（httpx 全缓冲，无流式截断）。
- DNS rebinding 连接侧 TOCTOU 未完全消除（base_url 非客户端输入，风险可控）。
- usage 部分字段缺失时对应项记 0（上游异常行为，非攻击路径）。
- Executor 角色模型路由已配置但 M3-C 前不启用。

## 10. 演示产物（artifacts/demo/）

- m3a_providers.txt：provider 与角色路由（不含 Key）
- m3a_provider_health.txt：status=disabled（real 未启用）
- m3a_dry_run.txt：预计模型调用与预算（不真正调用）
- m3a_fake_run.txt：fake 模式 github_compare_team → completed
- m3a_real_rejected.txt：real 模式未启用 → 明确拒绝（BLOCKED_BY_CREDENTIALS 证明）
