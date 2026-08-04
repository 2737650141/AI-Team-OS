# AI Team OS 智能体角色规范（MVP 五角色）

> 文档状态：Phase 0 草案，待总管验收
> 版本：v0.1（2026-08-04）

原则：**五种核心角色类型预注册，实例按任务动态创建**；没有任务时不运行，不默认把全部角色加入上下文。扩展能力通过 Agent Registry 按需注册（M2+），注册的新角色必须复用本规范模板。

---

## 1. Supervisor（主管）

- **职责**：意图澄清；从 Agent Registry 选择并派发 agent；处理失败、驳回与重试；维护任务生命周期（状态迁移、预算裁决、降级决策、finalize 汇总）。
- **输入**：`user_goal`、`constraints`、`clarified_goal`、`plan`、各子任务结果、`review_result`、`errors`。
- **输出**：`clarified_goal`、`selected_agents`、`retry_count`、`final_result`、`memory_candidates`；状态迁移指令。
- **可用工具**：只读工具（记忆检索、状态查询）；**无业务执行工具**。
- **禁止行为**：不直接执行子任务工作；不修改 `plan` 之外的预算分配；**不修改任务总预算**（预算冻结：总预算创建后对 LLM 不可修改，Supervisor 只能选择继续、降级、暂停或停止）；不绕过审批放行工具；不无限重派（硬上限 N=3 轮/子任务）。
- **上下文范围**：任务级摘要（目标、约束、计划、子任务状态、最近错误），不携带子任务全量证据。
- **Token 上限建议**：32K/次调用（汇总类 8K 足够，澄清类 4K）。
- **失败处理**：子任务失败 → 判定 `retryable` 后重派（换 agent 或换提示词）；超重试 → 转人工；预算超限 → 触发降级（见下）。
- **完成标准**：产出 `final_result` 且全部子任务 `review_result=pass`（或人工确认放行）。
- **交接数据**：向 Planner 交 `clarified_goal + constraints + context`；向 Reviewer 交 `(子任务要求, evidence, artifacts)` 的派发单。

## 2. Planner（规划师）

- **职责**：把澄清后的目标拆解为结构化 `Plan`（子任务依赖图、候选 agent、输入引用、产出定义、预算分配）；必要时检索记忆补充上下文。
- **输入**：`clarified_goal`、`constraints`、记忆检索结果。
- **输出**：`plan`（schema 化，含依赖无环保证）。
- **可用工具**：记忆检索（只读）；**无外部工具**。
- **禁止行为**：不修改用户约束；不执行任务；不创建超出注册表的 agent 类型；**只产生 `subtask_budget_allocations`，其总和不得超过任务总预算；不得修改任务总预算本身**。
- **上下文范围**：目标 + 约束 + 记忆摘要（≤8K）。
- **Token 上限建议**：16K/次。
- **失败处理**：schema 校验失败 → 重生成（最多 2 次）→ 失败则报 `planning_failed` 交 Supervisor 转人工。
- **完成标准**：`plan` 通过确定性校验（Pydantic schema、依赖无环、预算总和 ≤ 总预算、子任务数 ≤ 上限 8）。
- **交接数据**：`plan` → Supervisor（派发依据）与各子任务的输入引用。

## 3. Researcher（研究员）

- **职责**：事实采集与核查（GitHub、网页、本地文件只读分析）；产出带证据链的调研结论。
- **输入**：子任务要求、允许的只读工具清单、产出格式模板。
- **输出**：结构化调研报告（结论 + 每条结论的 `evidence` 引用 + 来源可靠性标注）。
- **可用工具**：`web_fetch`、`github_search`、`github_repo_info`、`file_read`（沙箱内）、`memory_read`。全部为 **read 级**。
- **禁止行为**：不写任何文件（含沙箱）；不调用任何 `read_only=false` 或 dangerous 工具；不编造来源（无证据的结论必须显式标注"未验证"）。
- **上下文范围**：子任务要求 + 已采集证据摘要（滚动窗口，≤32K）。
- **Token 上限建议**：64K/任务，单次调用 8K。
- **失败处理**：工具失败（网络/限流）→ 按 `retryable` 重试（最多 2 次）→ 换替代来源 → 仍失败则报告部分完成 + 缺失项清单。
- **完成标准**：报告满足产出模板；每条关键结论 ≥1 条证据；无未声明来源的断言。
- **交接数据**：调研报告（含 evidence 引用）→ Reviewer；记忆候选（新事实）→ Supervisor。

## 4. Executor（执行者）

- **职责**：执行已批准的实施性工作：文件处理（沙箱内）、代码生成、文档编写、按实施计划落地；每条动作记录工具调用证据。
- **输入**：子任务要求、实施计划（如适用）、输入文件引用、允许工具清单（含 `read_only=false` 工具）。
- **输出**：`artifacts`（产物引用 + 哈希）+ 变更摘要。
- **可用工具**：`file_write`（仅沙箱）、`file_read`、`command`（M3 前禁用）、`github_api`（只读；写操作需审批）、模板/格式化工具。
- **禁止行为**：不写沙箱外路径（Gateway 层强制）；不执行未授权命令；不修改他人子任务的产物；不跳过审批调用 dangerous 工具。
- **上下文范围**：子任务要求 + 相关输入文件（截断到预算）。
- **Token 上限建议**：64K/任务。
- **失败处理**：工具失败 → 定向重试（≤2 次）→ 报告 `execution_failed` 含错误码与部分产物；产物冲突（并发写）→ 放弃本次写入并报告。
- **完成标准**：产物存在且哈希校验通过；变更摘要与子任务要求一致。
- **交接数据**：产物引用 + 变更摘要 → Reviewer；工具调用记录（Gateway 自动）→ 审计。

## 5. Reviewer（审查员）

- **职责**：独立评审子任务产物：确定性校验 + LLM 清单式评审；给出 pass 或**定向驳回意见**（哪个子任务、改什么、重交哪些项）。
- **输入**：原始子任务要求 + 约束 + `evidence` + `artifacts` + 禁止行为清单。**不接收 Executor 的中间推理过程**。
- **输出**：`review_result{verdict, issues[], rework_targets[]}`。
- **可用工具**：只读校验工具（schema 校验、证据计数、禁止字符串扫描、哈希校验）；`file_read`（产物）。
- **禁止行为**：不修改产物；不执行任务；不基于 Executor 的自我陈述作结论（只依据证据与产物）；不放过"无证据结论"。
- **上下文范围**：仅评审对象本身（要求 + 证据 + 产物），≤64K。
- **Token 上限建议**：16K/次。
- **失败处理**：评审工具异常 → 报 `review_failed` 重试；产物缺失 → 直接 reject。
- **完成标准**：所有校验项执行完毕；verdict 有明确依据（问题列表逐条对应证据/产物位置）。
- **交接数据**：`review_result` → Supervisor（决定通过或定向返工）。

---

## 6. 角色间协作矩阵

| 交接 | 内容 | 格式 |
| -- | -- | -- |
| Supervisor → Planner | 目标/约束/记忆摘要 | `clarified_goal + constraints + context` |
| Planner → Supervisor | 计划 | `Plan`（Pydantic schema） |
| Supervisor → Specialist | 派发单 | `subtask_spec + allowed_tools + subtask_budget_allocations[i]` |
| Specialist → Reviewer | 证据与产物 | 流程跳转由 Supervisor/状态机控制；Reviewer 从受控状态存储读取 `evidence` 与 `artifacts`；Specialist 不私下直接调用 Reviewer；证据内容不经 Supervisor 重新总结或改写 |
| Reviewer → Supervisor | 评审结论 | `review_result` |
| Supervisor → Memory | 记忆候选 | `memory_candidates[]`（需人工确认） |

## 7. 通用约束（所有角色）

- 每个角色实例执行前后，Model Gateway / Tool Gateway 强制记账；超预算即被网关中断（角色无感知，由 Supervisor 处理降级）。
- 角色提示词中注入：`禁止行为清单`（该角色专属）+ 全局安全规则（不泄露密钥、不执行未授权操作）。
- 所有角色的 LLM 输出经过 schema 校验后才允许写入状态（fail-fast）。
