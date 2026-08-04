# AI Team OS 实施任务图

> 文档状态：Phase 0 草案，待总管验收
> 版本：v0.1（2026-08-04）
> 说明：本图给出里程碑、任务、依赖、交付物与验收条件，**不提供虚假精确工期**。每个里程碑以"迭代周"为粒度估算，实际节奏以总管验收与团队产能为准。

## 总原则

- 每个里程碑独立可验收（验收条件见下），验收通过后才进入下一阶段。
- 可并行部分列出以利排程，但**不得跳过阶段验收**。
- 安全与预算的确定性防线（RISK_REGISTER R02/R03/R04/R08）从 M1 起随内核一起落地，不后置。

---

## M0 基础仓库和工程规范

- **任务**：git 仓库初始化（`git init`，不 push）；目录结构（`app/`、`docs/`、`tests/`、`sandbox/`）；pyproject.toml（Python 3.11+ 兼容，锁定 3.12 目标）；ruff/black/mypy/pytest 配置；`.env.example`（无真实密钥）；CI 骨架（GitHub Actions 或本地脚本）。
- **依赖**：无（Phase 0 规划文档为输入）。
- **交付物**：可 `pip install -e .` + `pytest` 空跑通过的骨架仓库；CONTRIBUTING/工程规范文档。
- **验收条件**：`pytest` 通过；`ruff check` 通过；仓库无敏感文件（扫描脚本）。
- **预计风险**：环境差异（本机 Python 3.11.9 vs 目标 3.12）→ 兼容性先按 3.11 开发、CI 双版本测试。
- **可并行部分**：工程规范文档与 CI 配置。
- **本阶段不做**：任何业务代码、依赖安装到 LangGraph（M1 再做）。

## M1 单智能体最小执行内核（范围以总管令 002 与 002-A 为准）

- **任务**：
  - Model Gateway：Provider 接口定义 + **DeterministicFakeModel** + 预算记账（唯一权威入口）。
  - **最小 ToolSpec**（`risk_level: safe|sensitive|dangerous` + `read_only` + `requires_approval`）。
  - **FixtureRepositoryLookupTool**（本地 Fixture 仓库元数据，不访问网络）、**DangerousWriteTool**（M1 中 handler 永不执行）。
  - **Tool Gateway**（权限拦截）、**Budget Controller**、**Audit Log**（JSONL）。
  - **SQLite Checkpoint**（langgraph-checkpoint-sqlite）、**CLI**、**最小 FastAPI**。
  - 真实 Provider 只保留接口定义，不作为 M1 验收条件。
- **依赖**：M0。
- **交付物**：CLI（`ai-team-os run "目标"`）+ 最小 FastAPI（任务创建/查询）+ SQLite Checkpoint + 审计日志；pytest 覆盖权限拦截、硬预算、恢复。
- **验收条件**：DangerousWriteTool 被拦截且 handler 执行次数 = 0（GT-10 M1）；DeterministicFakeModel 测试中实际消耗不超过硬预算（GT-09，无容差）；权限拦截和恢复测试全绿；预算超限后任务强制终止；日志完整。
- **预计风险**：供应商 API 差异 → 接口定义先行，M2 起以适配器测试矩阵覆盖（删除 M1 的"至少调用 OpenAI 和另一个真实兼容端点"要求）。
- **可并行部分**：Model Gateway 接口与 ToolSpec/工具可并行开发。
- **本阶段不做**：真实 MCP 客户端、真实网络工具、真实 GitHub API、真实工具审批放行执行、多智能体、长期记忆、前端、Docker、PostgreSQL、Redis。

## M2 LangGraph 多智能体流程

- **任务**：Planner/Researcher/Reviewer 三个角色落地（AGENT_ROLES）；Plan schema 与确定性校验（无环/预算）；并行子图（fan-out/fan-in，subtask 分片写入）；Reviewer 双轨评审；定向返工链路（retry_count）；HITL interrupt（澄清）；SQLite Checkpoint 持续使用（M0-M3 一律 SQLite）。
- **依赖**：M1。
- **交付物**：`Supervisor→Planner→(并行)Specialist→Reviewer→(驳回→返工)→finalize` 完整链路；API 层（FastAPI REST + SSE）接入。
- **验收条件**：GT-01、GT-02、GT-05、GT-07、GT-11 自动验收通过（≥80% 断言绿）。
- **预计风险**：并行 reducer 冲突（R06）→ 状态分片写入先行单测；SSE 与 interrupt 交互。
- **可并行部分**：Reviewer 评审清单与 Planner schema 可并行。
- **本阶段不做**：写文件工具、沙箱、记忆系统、审批（工具类）。

## M3 工具、权限和沙箱

- **任务**：Tool Gateway（ToolSpec 统一模型 + 权限分级 `safe|sensitive|dangerous` + `read_only`）；MCP 客户端适配器；Permission & Approval Service（审批流 + 控制台 API）；Sandbox Service v1（**目录沙箱，命令执行保持禁用**）；文件锁（R07 防线）；密钥脱敏（R09 防线）。
- **依赖**：M2。
- **交付物**：`web_fetch`/`github_search`/`file_read`/`file_write(沙箱)` 等首批工具；审批 API 与 SSE 事件；Docker 沙箱设计文档（含 R08 风险评估）。
- **验收条件**：GT-03（只读约束）、GT-08（失败恢复）、GT-10（审批）自动验收通过；越权调用被硬拦截（R04 测试）。
- **预计风险**：MCP 工具 schema 差异 → 适配器兼容层；审批与中断恢复的交互。
- **可并行部分**：MCP 适配器与审批服务可并行。
- **本阶段不做**：任意命令执行、Docker 沙箱实装（单独子里程碑，需总管批准）。

## M4 记忆系统

- **任务**：Memory Service（项目级记忆 CRUD + 检索）；memory_candidates 人工确认流；**本里程碑引入 PostgreSQL 主库（含 checkpoint 切换）与 pgvector 扩展**；向量化检索（embedding 经 Model Gateway）；跨任务记忆注入（GT-02 上下文）。
- **依赖**：M2 + M3（审批流复用）；PostgreSQL/pgvector 按 002-A 时间线于本里程碑引入。
- **交付物**：记忆写入/检索 API；检索结果注入 Planner/Supervisor 上下文；pgvector 索引。
- **验收条件**：GT-02 上下文含历史记忆；记忆写入均经确认流；检索相关性抽检通过。
- **预计风险**：embedding 供应商依赖 → 抽象 EmbeddingProvider；向量检索质量。
- **可并行部分**：pgvector 方案验证与记忆确认 UI。
- **本阶段不做**：跨项目记忆、自动摘要记忆（后续）。

## M5 运行控制台

- **任务**：Next.js 最小管理界面（任务创建/进度 SSE/审批操作台/结果与证据/运行日志）；后端补 API 缺口（分页、筛选）；OTel 追踪接入（可选开关）。
- **依赖**：M3（审批 API）+ M4（记忆查看）。
- **交付物**：可演示的控制台页面（ChatDev 式运行展示借鉴，但保持最小）。
- **验收条件**：端到端人工演示通过：创建任务→实时进度→审批→结果查看；12 项黄金任务可从 UI 触发。
- **预计风险**：前后端联调成本 → API 契约先行（OpenAPI）。
- **可并行部分**：页面与后端补口可并行。
- **本阶段不做**：可视化图编排器、多用户权限管理。

## M6 黄金任务评测

- **任务**：黄金任务评测框架（pytest 脚本驱动 12 任务，本地 fixture 服务）；自动验收断言实现（GOLDEN_TASKS 全部自动验收项）；批次报告（通过率/token/cost/耗时）；回归 CI（每日 + 依赖升级时）。
- **依赖**：M1-M5 全部能力。
- **交付物**：`tests/golden/` 全套 + 评测报告模板；GT-01 到 GT-12 全量跑通。
- **验收条件**：自动验收通过 ≥9/12（GT-01/03/10/11 必过）；连续 3 次运行稳定（无 flaky）。
- **预计风险**：fixture 脆弱 → 隔离沙箱 + 确定性 fixture。
- **可并行部分**：各黄金任务断言独立编写。
- **本阶段不做**：大规模评测集、真人基准（后续）。

## M7 桌面与安卓扩展预留

- **任务**：接口预留评审（事件流/状态 API 是否支撑外部入口）；移动/桌面入口的架构预留文档；可选：CLI 增强（作为桌面入口原型）。
- **依赖**：M5。
- **交付物**：扩展预留设计文档；外部入口适配层接口草案。
- **验收条件**：文档评审通过；MVP 不实装任何系统级控制。
- **可并行部分**：无（低优先级，可延后启动）。
- **本阶段不做**：安卓系统级控制、Windows 桌面自动化、语音（明确排除在 MVP 外）。

---

## 依赖总览

```text
M0 ─→ M1 ─→ M2 ─→ M3 ─→ M4 ─→ M5 ─→ M6
                              └─→ M7（预留，低优先级）
```

## 建议的排程约束（非承诺工期）

- M0-M3 为"可运行内核"阶段，优先保证 GT-01/03/08/10/11 五条核心链路；基础设施时间线：M0-M3 一律 SQLite Checkpoint，PostgreSQL 于 M4 或刚需时引入，pgvector 于 M4 向量检索启用时引入，Redis 出现队列/跨进程锁/多实例需求后再决定，Docker Compose 仅作部署选项。
- M4 记忆与 M5 控制台互不阻塞，可交错；M6 评测最好与 M3 并行开始写断言骨架。
- 每个里程碑结束必须向总管提交验收证据（测试结果 + 演示），**不自动进入下一阶段**。
