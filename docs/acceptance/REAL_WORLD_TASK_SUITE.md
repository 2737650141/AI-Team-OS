# REAL_WORLD_TASK_SUITE — 真实用户任务套件

> PHASE: PRODUCT-01（纠偏令 020 第五节）
> 用途：以"普通用户真实输入"验收 AI Team OS 是否真的能用，而非用测试数量证明质量。
> 判定标准：`USER ASKED → JARVIS UNDERSTOOD → JARVIS COMPLETED`。

## 一、为什么需要这份套件

过去大量测试只证明 `COMPONENTS_WORK`，不能证明 `PRODUCT_WORKS`。
真实案例（任务 `9379b0e1950b`，用户输入"帮我查一个 guthub 上热门的项目"）：

```
Planner → Reject → Rework → Reject → Rework → Reject → Task Failed
```

根因：Planner 分配了运行时不可执行角色 → plan_validator 未拦截 → 执行期
`unsupported role` 盲重试 3 次 → `rework_limit_exceeded`。
修复后重放：`Task Completed`（SIMPLE 快速路径，2 个 researcher 并行，0 盲重试）。

本套件用于**防止同类产品级失败回归**，并按纠偏令要求回答：

> 普通人随便用，它到底能不能完成事情？

## 二、分级标准（TaskComplexityClassifier 对齐）

| 级别 | 数量 | 说明 | 期望编排 | 成功率门槛 |
|------|------|------|----------|------------|
| Level A (Simple) | 15 | 一句话任务，无需澄清，直接完成 | Supervisor → Researcher（单步）→ Result；禁止 4 subtasks + 全五 Agent | **15 / 15（100%）** |
| Level B (Standard) | 20 | 普通任务，允许多 Agent 协作 | Supervisor → Planner → Researcher(optional) → Executor → Reviewer | ≥ 19 / 20（95%） |
| Level C (Complex) | 15 | 复杂任务，允许完整编排与返工 | Supervisor → Planner → Researchers → Executor → Reviewer → Rework → Replan | ≥ 13 / 15（86%），失败必须可解释 |

复杂度由 `app/core/complexity.py::classify_task` 确定性判定，禁止针对本套件 hardcode。

## 三、Level A：最简单任务（15 个，必须 15/15）

普通用户期望：直接完成。禁止产生澄清 interrupt、禁止 Review 死循环、禁止模型调用浪费
（Simple 任务默认 model calls ≤ 4、rework ≤ 1，除非真实外部错误）。

| ID | 用户输入 | 预期结果 | 失败分类预期 |
|----|----------|----------|--------------|
| A01 | 帮我找几个最近热门的 GitHub AI Agent 项目。 | 返回 ≥2 个项目结论，带证据，任务完成 | INTENT_FAILURE / TOOL_FAILURE |
| A02 | 打开记事本写一句测试。 | （操作型，依赖 Windows 子系统）窗口操作完成或给出可读失败原因 | UI_FAILURE / PERMISSION_FAILURE |
| A03 | 看看我现在打开了哪些窗口。 | 返回窗口列表或可读原因 | UI_FAILURE |
| A04 | 这个项目主要用了什么技术？ | 给出技术栈结论（带证据） | TOOL_FAILURE |
| A05 | 帮我整理一下这个文件夹里的 Python 文件。 | 列出/整理结果 | TOOL_FAILURE |
| A06 | 看看这个页面有什么。 | 页面内容摘要 | TOOL_FAILURE / PROVIDER_FAILURE |
| A07 | 检查一下这个 Python 文件有没有明显问题。 | 问题清单或"未发现问题" | TOOL_FAILURE |
| A08 | 总结这个项目。 | 项目总结 | TOOL_FAILURE |
| A09 | 帮我找三个类似项目。 | 3 个类似项目结论 | TOOL_FAILURE |
| A10 | 运行一下测试看看有没有报错。 | 测试结果摘要 | TOOL_FAILURE / PERMISSION_FAILURE |
| A11 | 现在几点了？ | 时间回答，直接完成（TRIVIAL 空计划） | UNKNOWN |
| A12 | 帮我查一下 GitHub 上 stars 最多的 Agent 框架。 | 结论 + 证据 | TOOL_FAILURE |
| A13 | 列出当前目录下的文件。 | 文件列表 | TOOL_FAILURE |
| A14 | 介绍一下你自己。 | 简短介绍，直接完成 | UNKNOWN |
| A15 | 帮我看看这个仓库是干什么的。 | 仓库用途结论 | TOOL_FAILURE |

**语义变体**（每次执行轮换，验证 semantic robustness 而非 prompt memorization）：
- A01 变体："找几个热门 Agent 项目" / "GitHub 上最近有什么值得看的 AI Agent 开源项目？"
- A09 变体："帮我搜几个类似 JARVIS 的项目" / "看看最近 Agent 框架里哪些项目比较火"

## 四、Level B：普通任务（20 个，≥19/20）

允许 Planner / Researcher / Executor / Reviewer 协作；不允许把简单问题复杂化。

| ID | 用户输入 | 预期结果 | 失败分类预期 |
|----|----------|----------|--------------|
| B01 | 去 GitHub 找几个类似我们的多 Agent 项目，对比一下优缺点。 | 对比结论（≥2 项目、优缺点、带证据） | TOOL_FAILURE / ROLE_MISMATCH |
| B02 | 这个测试失败了，找原因并修好。 | 定位根因 + 修复 + 测试通过 | TOOL_FAILURE / EVIDENCE_POLICY_FAILURE |
| B03 | 检查项目代码结构，告诉我哪里设计得不好。 | 结构问题清单 | TOOL_FAILURE |
| B04 | 打开当前软件设置，把语言切换成英文。 | （操作型）完成或可读失败 | UI_FAILURE / PERMISSION_FAILURE |
| B05 | 看看项目依赖有没有明显重复。 | 重复依赖结论 | TOOL_FAILURE |
| B06 | 找出这个项目里最重要的几个模块。 | 模块清单 + 理由 | TOOL_FAILURE |
| B07 | 帮我分析一下这个项目的性能瓶颈可能在哪。 | 分析结论（带证据） | TOOL_FAILURE |
| B08 | 这个报错是什么意思？怎么解决？ | 解释 + 解决方案 | TOOL_FAILURE |
| B09 | 对比 langgraph 和 crewai 的 license 和活跃度。 | 对比结论 + evidence | TOOL_FAILURE |
| B10 | 帮我把这几个项目的 README 摘要整理成对比表。 | 对比表（Markdown） | TOOL_FAILURE |
| B11 | 检查一下代码里有没有明显安全问题。 | 安全问题清单 | TOOL_FAILURE |
| B12 | 这个函数太长了，建议怎么拆？ | 拆分建议 | TOOL_FAILURE |
| B13 | 帮我看看 CI 配置有什么问题。 | 问题清单 | TOOL_FAILURE |
| B14 | 哪些依赖可以升级？ | 升级建议（带版本证据） | TOOL_FAILURE |
| B15 | 这个项目支持哪些权限模式？分别是什么？ | 权限模式说明 | TOOL_FAILURE |
| B16 | 帮我检查 memory 系统的存储结构。 | 存储结构说明 | TOOL_FAILURE |
| B17 | 找出最近修改的文件并总结改动。 | 文件清单 + 改动摘要 | TOOL_FAILURE |
| B18 | 项目里有没有重复代码？ | 重复代码结论 | TOOL_FAILURE |
| B19 | 帮我梳理一下这个项目的错误处理逻辑。 | 错误处理梳理 | TOOL_FAILURE |
| B20 | 评估一下项目对 GitHub API 的依赖是否合理。 | 评估结论 | TOOL_FAILURE |

## 五、Level C：复杂任务（15 个，≥13/15）

允许完整编排：Planner → Researchers → Executor → Reviewer → Rework → Supervisor Replan。
失败必须**可解释**（禁止静默失败、禁止盲重试、禁止 unexplained failure）。

| ID | 用户输入 | 预期结果 | 失败分类预期 |
|----|----------|----------|--------------|
| C01 | 研究三个 GitHub 项目，然后结合我们的项目提出架构方案，不要直接改代码。 | 方案文档（不落盘代码） | BAD_PLAN / ROLE_MISMATCH |
| C02 | 发现失败测试，修复，运行测试，Reviewer 不通过就返工。 | 修复 + 测试通过 + review 历史完整 | REWORK_LOOP / REVIEWER_FALSE_REJECT |
| C03 | 检查一个模块的影响范围，提出最小修改方案，再执行。 | 影响范围 + 方案 + 最小改动实施 | BAD_PLAN |
| C04 | 帮我把 Agent 协作流程改成支持并行研究，评估对现有测试的影响。 | 改造方案 + 影响评估 | BAD_PLAN / TOOL_FAILURE |
| C05 | 调研三种记忆方案，结合项目现状写一份技术选型报告。 | 选型报告 | TOOL_FAILURE |
| C06 | 重构这个模块并保证全部测试通过，先给方案再动手。 | 方案 + 重构 + 测试通过 | REWORK_LOOP |
| C07 | 对比国内外 5 个多 Agent 框架，写对比报告并给落地建议。 | 对比报告 | TOOL_FAILURE |
| C08 | 分析权限系统在多用户场景的缺口，提出加固方案。 | 缺口分析 + 方案 | BAD_PLAN |
| C09 | 帮我做一个性能优化方案：先测量再改，改完验证。 | 测量数据 + 改动 + 验证 | TOOL_FAILURE / REWORK_LOOP |
| C10 | 设计一个日志审计方案并实现核心部分。 | 方案 + 核心实现 | BAD_PLAN |
| C11 | 评估引入向量数据库的收益与风险，给出决策建议。 | 评估报告 | TOOL_FAILURE |
| C12 | 把项目从单机部署改造成可扩展架构，输出改造计划。 | 改造计划 | BAD_PLAN |
| C13 | 对现有测试体系做一次审计，找出工程健康盲区并修复最严重的一个。 | 审计报告 + 修复 | REWORK_LOOP |
| C14 | 研究 openai-compatible 协议差异，确保我们 provider 兼容性并补测试。 | 差异分析 + 补测 | TOOL_FAILURE / BAD_PLAN |
| C15 | 制定项目下一阶段里程碑，按风险排序并给出实施顺序。 | 里程碑计划 | BAD_PLAN |

## 六、执行要求（不得违反）

1. **真实用户输入**：使用上表原文或指定变体，禁止工程师式 Prompt、禁止 expected_plan/fixture_plan。
2. **真实 Provider**：Level B/C 优先真实模型（如 DeepSeek）；fake 模式只允许作为离线回归基线，
   必须在报告中显式标注 `model_mode`。当前环境无 `AI_TEAM_MODEL_*` 配置时，先跑 fake 基线，
   配置后复验 real（见 `docs/operations/REAL_MODEL_SETUP.md`）。
3. **真实工具**：GitHub 用真实 GitHub Tool/MCP/API；Windows 用真实 Windows Action；
   项目用真实 Workspace。危险操作（写文件/网络/权限）使用独立测试目录。
4. **Permission Mode**：以 STANDARD 为主；额外 SAFE 5 个、MAXIMUM 5 个，确认权限系统不破坏普通工作流。
5. **禁止 Hardcode**：Reviewer 必须检查 special case / prompt string match / task-specific bypass /
   hardcoded output，发现即 Blocking。
6. **随机变体**：除固定 50 个任务外，每次验收另跑 20 个语义变体（由独立模型生成，执行模型不可预读）。
7. **连续会话**：至少一次 10-turn session（找项目 → 第二个详细看看 → 跟我们的比一下 → 哪些值得借 →
   先别改代码 → 写个方案 → 继续 → 把第一项实施 → 看一下结果 → 还有问题吗），验证
   Working Context / Memory / Current Goal / Reference Resolution。

## 七、指标记录（每次 PRODUCT-01 验收必填）

每个任务记录：

```yaml
id: A01
user_input: "帮我找几个最近热门的 GitHub AI Agent 项目。"
level: A
model_mode: fake|real
permission_mode: standard|safe|maximum
status: completed|failed|paused
failure_code: null|INTENT_FAILURE|BAD_PLAN|ROLE_MISMATCH|TOOL_FAILURE|EVIDENCE_POLICY_FAILURE|REVIEWER_FALSE_REJECT|REWORK_LOOP|MODEL_FORMAT|CONTEXT_FAILURE|PROVIDER_FAILURE|PERMISSION_FAILURE|UI_FAILURE|UNKNOWN
model_calls: <int>
tool_calls: <int>
rework_count: <int>
replan_count: <int>
time_to_result_s: <float>
notes: <人工可读补充>
```

汇总输出（见 `docs/acceptance/PRODUCT01_REPORT.md` 模板）：
- Simple / Standard / Complex 成功率
- Failure Taxonomy 聚类（优先修高频根因，不逐个打补丁）
- 平均 model calls / tokens / latency（Simple）
- UX：unexplained failures、可读失败原因、Retry、Replan

## 八、门禁（纠偏令 041）

```
Simple:           15 / 15
Standard:         ≥ 19 / 20
Complex:          ≥ 13 / 15
Top 10 Smoke:     10 / 10
Critical security: 0 failures
Silent fallback:   0
Unexplained failure: 0
Blind 3x retry:    0
```

最终状态：`PRODUCT_BASELINE_VALIDATED`，否则禁止开始 M7。
