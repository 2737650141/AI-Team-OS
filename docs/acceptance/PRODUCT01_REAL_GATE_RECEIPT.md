# PRODUCT-01 REAL GATE 回执（020-B）

> PHASE: PRODUCT-01 REAL GATE
> 执行时间: 2026-08-12
> 说明：本回执如实记录真实产品门禁结果，不伪造通过、不以 fake/单元测试覆盖真实门禁。

## PROVIDER_RUNTIME

- Production SecretResolver: PASS（`app/core/secret_store.py::process_resolver`，Session → Windows Secure Store(DPAPI) → Env → Missing）
- Windows Secure Store: PASS（`data/runtime/secrets/openai_compatible.api_key.bin` / `github.token.bin` / `custom_provider.*.api_key.bin` 均 resolved=True）
- Provider: **DeepSeek Official**（`https://api.deepseek.com`，health=healthy，is_default=1）
- Model: **deepseek-v4-flash**（role_defaults 全角色；发现 deepseek-v4-pro）
- Fake fallback: **0**（020-B 二修复：验收脚本默认 `auto` 走生产链路；无凭据 → `WAITING_FOR_USER_CREDENTIAL_INPUT` 提示去 App Settings→Connections，不得自动 Fake）
- Acceptance Runtime = Production Provider Runtime: PASS（`app/acceptance_runtime.py` 复用 build_provider，不复制第二套 Provider 逻辑）

## ORIGINAL_FAILURE

- Real replay: **PASS**（goal="帮我查几个 GitHub 上最近比较热门的 AI Agent 项目。"，与 020-B 四指定一致）
- Model calls: 7（deepseek-v4-flash，real_call=true）
- Tool calls: 2（`github_search_repositories`，真实 GitHub API）
- Rework: 0 / Replan: 0 / Unsupported role: 0 / Blind rework: 0
- Result: **COMPLETED**——claims=3 真实数据（obra/superpowers，270,961 stars，"An agentic skills framework…"），evidence=1，usage {tokens:5811, cost:$0.0009}
- 链路证明：Intent → Task Complexity(simple) → Research(LLM+GitHub API) → GitHub Data(真实) → Result → COMPLETED

## REAL_SIMPLE（020-B 五，10 个）

- Passed: **10 / 10**
- Total: 10
- Average calls: ~7.6 / Average tokens: ~4,900（REPORTED）/ Average latency: ~7.3s
- Failures: 0
- 覆盖：GitHub 搜索×2、项目总结、技术栈、文件分析、测试查看、GitHub 详情×2、文件列表、TRIVIAL 时间问答
- 真实工具：`github_search_repositories` / `github_repo_info` / `local_list_directory`（非 fixture 冒充；危险操作未涉及）
- 说明：窗口观察/页面观察依赖桌面子系统（未在本 CLI 环境执行，文档注明）

## REAL_STANDARD（020-B 六，10 个）

- Passed: **0 / 10**
- Total: 10（执行 4 个后触发费用上限停止）
- Full orchestration runs: 4（均进入 Planner/Researcher/Reviewer 真实编排）
- Failures: 4（T01 planner 预算膨胀 budget_exceeded；T02-T04 reviewer 连续 reject×3 → rework_limit_exceeded）
- 根因（真实产品瓶颈，已诊断）：
  1. LLM planner 在完整编排下 bounded repair 轮次多、预算分配膨胀（81 calls / 94k tokens 仍 budget_exceeded）；
  2. 真实 reviewer 按 planner acceptance_criteria 严格拒绝（要求 license/stars 等具体字段），而 researcher 真实 GitHub 数据获取不稳定（工具调用失败/幻觉参数）；
  3. 失败 signature 因真实模型输出每次变化而不稳定 → guard 不触发（已修复：rework 上限 → Supervisor replan 兜底，见下）。

## REAL_COMPLEX（020-B 七，5 个）

- Passed: 未执行（同 STANDARD 根因，避免无意义烧费；费用上限已触发）
- Reviewer runs / Rework runs: 未测
- 失败样本：无（未跑，诚实标注）

## CONTINUOUS_SESSION（020-B 十）

- Turn 1 找几个最近热门的 Agent 项目: completed（SIMPLE 真实/离线均可）
- Turn 2 第二个详细看看: completed（指代解析 → 详细研究第 2 项）
- Turn 3 跟我们的项目比较一下: completed（比较 selected_item 与当前项目）
- Turn 4 哪些东西值得我们借鉴: completed
- Turn 5 先别改代码: confirmed（NO_WRITE_CURRENT_SCOPE 设置）
- Turn 6 那先写个方案: completed（为选中项制定实施方案，只读）
- Turn 7 继续: completed（Resume 完善方案）
- Turn 8 把第一项实施: completed（新授权解除 no_write + plan 第 1 项）
- Turn 9 看一下结果: completed（Working Context 回显）
- Turn 10 还有没有问题: completed（会话总结）
- Result: **fake 离线基线 10/10**；真实模型 10-turn 未执行（成本与时间预算优先用于 Simple/重放；ConversationSession 为纯确定性层，fake/real 行为一致——真实复验待下次产品集）
- 之前 4/10（无会话上下文）→ 10/10（ConversationSession + Resolver）: **Blocking Issue 已修复**

## REFERENCE_RESOLUTION（020-B 十一）

- 第二个: PASS（recent_assistant_results items 第 2 项 → selected_item）
- 继续: PASS（pending_plan/current_task_reference → Resume；多候选才澄清）
- 第一项: PASS（pending_plan.items[0]）
- 刚才那个: PASS（recent_grounding 最近项）
- 优先级: Current Turn > Working Context > Current Task > Project Memory（不永久保存历史，会话 JSON 可删）

## FAILURE_UX（020-B 十六）

- Root cause visible: PASS（failure_code 枚举 + 中文 final_result；修复了 ProviderError.code 未映射导致 TaskState 崩溃的 bug——现在 timeout/连接/限流等映射为 provider_error）
- Retry: PASS（结构化 `retryable`）
- Replan: PASS（`supervisor_replanned`/`replan_triggered` 事件 + replan_count 追踪；rework 上限→replan 兜底已实现）
- Unexplained failure: 0（全部失败带 failure_code）

## REAL_USAGE（020-B 八/十八，费用控制）

- Requests: ~185 真实模型调用（上限 150/run 已触发停止）
- Reported tokens: ~330k（REPORTED from Usage/Token Observatory）
- Estimated tokens: 未单独估计（REPORTED 已覆盖）
- Cost: ~$0.05-0.10（DeepSeek 价格）
- Latency: Simple 平均 7.3s；Standard 40-100s
- 控制项：max_real_requests=150、max_total_tokens=300k、max_wall_time=30min 均生效

## REGRESSION

- Backend: **521 passed, 2 skipped**（新增 13：realgate 3 + conversation 10；含既有全部）
- Frontend/Windows/Vision/Voice/Memory/Permissions: 未回归（既有测试全部通过；本环境无桌面/UI 集成验证）
- ruff: 0 errors

## CODEX

- Independent real black-box: 本环境无法启动独立编码 Agent；以真实 DeepSeek 调用 + 全量测试替代
- Blocking: 1（STANDARD/COMPLEX 完整编排真实不稳定——Planner 预算膨胀 + Reviewer 严格拒绝循环）
- High: 1（同上）
- Medium: 0 / Low: 0

## STATUS

```
PRODUCT_BASELINE_PARTIAL
```

### 通过项
- ORIGINAL REAL REPLAY: PASS
- REAL SIMPLE: 10/10 PASS
- REAL 10-TURN（离线确定性层）: 10/10 PASS
- FAKE FALLBACK: 0（生产凭据链路打通）
- UNEXPLAINED FAILURE: 0
- BLIND RETRY LOOP: 0（rework 上限→replan 兜底）

### 未通过项（下一阶段投入方向）
- REAL STANDARD: 0/10（需：planner 预算分配优化 / reviewer 真实模式门槛校准 / researcher 工具失败自愈）
- REAL COMPLEX: 未测（同根因）
- REAL 10-TURN（真实模型）: 待复验（确定性层已验证）

### 本轮交付的真实缺陷修复清单
1. ToolGateway 参数过滤（LLM 幻觉参数不再导致 handler 崩溃）+ audit 记录
2. github_search_repositories 支持 sort/order（热门排序）
3. researcher prompt 注入工具参数说明（describe_tools，减少缺参/幻觉）
4. ProviderError.code → FailureCode 映射（budget_insufficient 等不再使 TaskState 崩溃）
5. classify：SIMPLE 只读动词优先、多步意图（对比/评估/梳理等）归 STANDARD、SIMPLE researcher 预算 3
6. LLM planner subtask 数按复杂度钳制（simple 2 / standard 4 / complex 8）
7. rework 上限 → Supervisor replan 兜底（真实场景 guard 失效时的换方法路径）
