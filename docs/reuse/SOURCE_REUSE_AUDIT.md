# 开源源码级复用审计（SOURCE REUSE AUDIT）

> 文档状态：主管令 003，任务 B + 任务 C
> 审计时间：2026-08-05
> 审计 HEAD：`50e0663`
> 方法：**源码级检查**（读取上游仓库实际源码/公开 API/扩展点），非 README 复述。
> 候选上游：`langchain-ai/langgraph`、`openai/openai-agents-python`、`crewAIInc/crewAI`、
> `OpenBMB/ChatDev`、`FoundationAgents/MetaGPT`、`microsoft/agent-framework`

---

## 0. 复用分类定义（主管令 B-02）

| 分类 | 含义 |
| -- | -- |
| `DIRECT_DEPENDENCY` | 直接使用官方包和 API |
| `WRAPPER_ADAPTER` | 不复制核心代码，只在外层增加本项目治理 |
| `SUBCLASS_EXTENSION` | 继承官方扩展点 |
| `SELECTIVE_CODE_REUSE` | 复制少量源码并保留许可证、来源、修改记录 |
| `DESIGN_REFERENCE_ONLY` | 只借鉴思路，自行实现 |
| `REJECT` | 不采用，并说明原因 |

**架构铁律**：单一编排核心 = LangGraph。禁止 CrewAI / Microsoft Agent Framework / OpenAI Agents SDK 成为第二编排核心。治理（审批、硬预算、审计）留在 LangGraph 节点外层确定性代码。

---

## 1. LangGraph（langchain-ai/langgraph）代码级检查

> 已直接依赖：`langgraph>=1.2,<2.0`（已装 **1.2.10**），`langgraph-checkpoint-sqlite`（**3.1.1**）
> 检查方式：读取 `.venv/Lib/site-packages/langgraph/` 实际源码 + 官方 API 签名验证。

### 1.1 逐能力对照（主管令 B-03）

| 能力 | 官方实现 | 当前 `app/` 是否重复实现 | 结论 |
| -- | -- | -- | -- |
| StateGraph | `langgraph.graph.StateGraph` | `app/graph.py` 正确使用官方 `StateGraph/START/END`；`_validate_checkpoint` 为项目扩展 | **DIRECT_DEPENDENCY** |
| Checkpointer | `langgraph.checkpoint.base.BaseCheckpointSaver` | `app/runner.py` 使用官方 `SqliteSaver`，无自研 | **DIRECT_DEPENDENCY** |
| SQLite Saver | `langgraph.checkpoint.sqlite.SqliteSaver` | 同左，直接 import | **DIRECT_DEPENDENCY** |
| interrupt 与恢复 | `langgraph.types.interrupt` / `Command(resume=...)` | M1 未使用（单节点原子图）；演示脚本验证原生可用 | **DIRECT_DEPENDENCY**（M2 直接使用） |
| Command | `langgraph.types.Command` | M1 未使用 | **DIRECT_DEPENDENCY** |
| ToolNode / 工具执行预构建节点 | `langgraph.prebuilt.tool_node.ToolNode` | `app/gateway/tool_gateway.py` **自行实现了工具执行/拦截循环**，与 ToolNode 重叠，但多出鉴权/幂等/审计治理 | **WRAPPER_ADAPTER**（见 §1.2） |
| 状态 reducer | `typing.Annotated[list, operator.add]` | `app/core/state.py` 的 `tool_calls/evidence/approvals` **未使用 Annotated reducer**（M1 单节点无 fan-in 需求） | **DIRECT_DEPENDENCY**（M2 升级） |
| 子图 | `StateGraph` 内嵌子图 | M1 未用 | **DIRECT_DEPENDENCY**（M2 用于 Specialist） |
| 并行 fan-out/fan-in | `langgraph.types.Send` / `Send API` | M1 未用 | **DIRECT_DEPENDENCY**（M2 用于并行子任务） |
| Streaming | `compiled.stream()` / `.astream_events()` | M1 未用 | **DIRECT_DEPENDENCY**（M2 API） |
| 错误重试/任务恢复 | `RetryPolicy`（`langgraph.pregel` 支持） | M1 无（单节点原子图）；`ToolGateway` 有幂等去重（R19） | **DIRECT_DEPENDENCY**（M2 用官方 RetryPolicy） |

### 1.2 关键判断（主管令 B-03 五问）

1. **当前 `app/graph.py` 是否重复实现官方能力？**
   否。`graph.py` 仅 31 行，用官方 `StateGraph` 搭单节点图，`_validate_checkpoint` 是项目 schema 版本护栏，非重复实现。→ `DIRECT_DEPENDENCY`。

2. **当前 `app/runner.py` 是否可直接使用官方运行接口？**
   基本可以。`compiled.invoke(...)` 即官方运行接口。runner 的职责是**装配**（budget/audit/gateway 注入 + checkpoint 连接管理），属薄包装，应保留。→ `WRAPPER_ADAPTER`（装配层保留）。

3. **当前 Checkpoint 封装是否有必要？**
   封装极薄（直接 `SqliteSaver(conn)`），有必要且正确。唯一项目扩展是 `TaskState.checkpoint_version` 版本校验（R18）。**注意**：`resume-demo` 中发现 `TaskStatus`（pydantic Enum）在 msgpack checkpoint 反序列化时触发 "Deserializing unregistered type" 警告，M2 需在编译时显式 `allowed_msgpack_modules` 或迁移 TaskStatus 为字符串通道，否则未来版本会硬拦截。

4. **哪些治理逻辑应留在 LangGraph 节点外层？**
   必须留在外层（确定性代码，LLM 不拥有安全决策权）：
   - 预算冻结/记账（`BudgetController`）——Model Gateway 唯一权威入口
   - 工具鉴权/拦截/幂等/审计（`ToolGateway`）——审批、脱敏、防重放
   - 审计日志（`AuditLog` + `redact`）——JSONL 证据链
   - ToolSpec 风险分级（`RiskLevel`/`read_only`/`requires_approval`）
   这些**不得**下沉到 LangGraph 节点内由 LLM 控制。

5. **哪些功能必须使用官方实现，不能自行维护？**
   StateGraph 构建、Checkpoint 持久化、interrupt/resume 语义、Send fan-out、streaming、RetryPolicy。自研这些无必要且引入兼容风险。→ `DIRECT_DEPENDENCY`。

### 1.3 LangGraph 上游缺陷登记（本审计实测）
- `langgraph 1.2.10`：`Command(resume=None)` 触发 `UnboundLocalError: resume_is_map`（`pregel/_loop.py:927`）。恢复必须传实际值。已在 M2 风险表登记。
- msgpack 对未注册 pydantic 类型（`app.core.state.TaskStatus`）反序列化警告，未来版本会变成硬错误。

---

## 2. OpenAI Agents SDK（openai/openai-agents-python）代码级检查

> 主管令 B-04。重点：**不引入第二编排核心**，只评估作为 Provider/工具适配层的可能。

| 能力 | 官方实现 | 与当前 `app/gateway/*` 对比 | 决策 |
| -- | -- | -- | -- |
| Agent | `agents.Agent`（被动配置 dataclass，驱动需 Runner） | 职责与未来 `Supervisor/Specialist` 角色配置重叠；**驱动它必须引入 Runner 编排** | `REJECT`（Agent 配置可参考，但执行需 Runner） |
| 工具 schema 抽取 | `agents.function_tool` / `FunctionTool` / `function_schema.py` | 纯函数→JSON schema 提取工具，**零 run-loop 耦合**；可喂给 LangGraph ToolNode | `DIRECT_DEPENDENCY`（可选官方 `openai-agents` 的 function_tool，或自用 griffe/pydantic） |
| Guardrails | `agents.InputGuardrail/OutputGuardrail`（dataclass + tripwire） | 本项目用确定性 `ToolGateway` + `BudgetController` 实现同类的"护栏"，但更偏向治理而非 LLM 校验 | `SELECTIVE_CODE_REUSE`（guardrail 包装器模式可借鉴，调度仍自研） |
| Sessions | `agents.sessions` / `SessionState` | 与 `TaskState` 概念重叠 | `DESIGN_REFERENCE_ONLY` |
| Handoffs | `agents.handoffs` | 与未来 Agent Registry/定向返工概念重叠 | `DESIGN_REFERENCE_ONLY` |
| Tracing | `agents.TracingProcessor` ABC + span-data | 与 JSONL 审计日志 + OpenTelemetry 预留重叠 | `SELECTIVE_CODE_REUSE`（span 归一化 schema 可借鉴） |
| Model Provider 接口 | `agents.models.Model/ModelProvider` ABC + `OpenAIProvider` | **可作为 Model Gateway 的 Provider 适配器**：`app/gateway/model_gateway.py` 的 `LLMProvider` Protocol 可薄适配 | `WRAPPER_ADAPTER`（仅 Provider 层） |
| MCP 集成 | `agents.mcp.MCPServerStdio/Sse/StreamableHttp` + `MCPServerManager` | M3 工具扩展点；provider 级操作（list_tools/call_tool）与 run-loop 解耦 | `WRAPPER_ADAPTER`（M3 评估；可包装 MCP server 为 LangGraph tool） |
| Human-in-the-loop | `agents.hitl` | 本项目用 LangGraph `interrupt()` 更贴合编排 | `REJECT`（编排核心已选 LangGraph） |
| Sandbox | `agents.sandbox.SandboxRuntime/BaseSandboxSession`（docker/unix_local） | M3 沙箱执行才需要；provider 级可独立驱动 | `WRAPPER_ADAPTER`（M3 DEFER 评估） |

**结论**：OpenAI Agents SDK **不整体引入**。仅其 `Model Provider` 接口可作为 Model Gateway 的 OpenAI-compatible 适配参考（本项目 M2 接入真实模型时可选用官方 `openai` SDK，或用 OpenAI-compatible HTTP 端点）。**不作为编排核心**，不把 `app/runner.py` 改为 `Runner.run()`。

---

## 3. CrewAI（crewAIInc/crewAI）代码级检查

> 主管令 B-05。目标：判断可复用的**配置格式/数据模型**，**不是**编排核心。

| 能力 | 官方实现 | 复用判断 | 决策 |
| -- | -- | -- | -- |
| Agent 配置（role/goal/backstory/llm） | `crewai.agent.Agent` 字段 | 数据模型清晰，可参考设计本项目 `AgentSpec`（`docs/planning/AGENT_ROLES.md` 已有雏形） | `DESIGN_REFERENCE_ONLY` |
| Task | `crewai.task.Task` | 任务模型与 `TaskState` 子任务结构可互相参考 | `DESIGN_REFERENCE_ONLY` |
| Crew 编排循环 | `crewai.crew.Crew.kickoff()` | **其内部编排循环不采用**（已有 LangGraph） | `REJECT` |
| Flow | `crewai.flow.Flow` / `@start/@listen` | 事件驱动流式编排；与 LangGraph 图语义重叠 | `REJECT`（避免第二编排语义） |
| 工具注册 | `@tool` / `crewai.tools.BaseTool` | 与 `ToolSpec` + LangChain `BaseTool` 思路相似 | `DESIGN_REFERENCE_ONLY` |
| 结构化输出 | `Task.output_pydantic` | 与 `pydantic` 状态 schema 一致思路 | `DESIGN_REFERENCE_ONLY` |
| YAML 配置格式 | `crewai.project` / `yaml` 配置 Agent/Task | **值得借鉴**：YAML 描述 Agent/Role/Task 是清晰的声明式约定，可参考（本项目未来可用 YAML 声明 Specialist 注册） | `SELECTIVE_CODE_REUSE`（仅格式约定，不复制代码）或 `DESIGN_REFERENCE_ONLY` |

**结论**：CrewAI 不 Fork、不引入。其 `Agent/Task/Role/Goal` **数据模型与 YAML 配置约定**作为设计参考，融入本项目 `AgentSpec`。工具注册模式（`@tool`/`BaseTool`）可作为 `ToolSpec` 桥接参考。**编排循环与 Flow 明确 REJECT**。

---

## 4. ChatDev（OpenBMB/ChatDev）代码级检查

> 主管令 B-06。目标：评估 M5 前端 Fork 决策。

| 问题 | 回答 |
| -- | -- |
| M5 是否应 Fork ChatDev 前端？ | **不建议完整 Fork**。 |
| 完整 Fork 还是提取部分页面/组件？ | **均不直接复用**。前端是 Vue 3 + Vite SPA（用 `@vue-flow`，React Flow 的 Vue 移植），页面为单体大文件（LaunchView ~98KB、WorkflowView ~70KB、FormGenerator ~75KB），样式内嵌、与 ChatDev 精确 REST/WS 端点紧耦合。技术栈与计划 Next.js/React 冲突。 |
| 它用 Vue，计划 Next.js/React，继续 Next.js 是否必要？ | **是，继续 Next.js**。本项目后端 FastAPI + SSE + 审批流，React/Next.js 生态与现有 API 集成更顺；为前端引入 Vue 会增加双栈负担。 |
| 采用 ChatDev 前端能减少多少工作？ | **有限**。直接复用 <20%；最大价值是**交互/信息架构参考**（任务进度树、状态徽标、日志流）而非代码。 |
| 二次开发继承哪些架构负担？ | Vue3/Vite 生态、页面单体耦合、与后端自定义 WS 协议强绑定、构建链与 Next.js 工程化冲突。 |
| Apache-2.0 的 NOTICE 与修改声明如何处理？ | 上游**无 NOTICE 文件**（GET /NOTICE → 404）。若借鉴其代码，须保留 Apache-2.0 头并记录修改；若仅参考设计，无需。本轮不创建前端，M5 再定。 |

**结论**：ChatDev 前端 **不 Fork，不引入**。本轮仅作设计参考评估（`DESIGN_REFERENCE_ONLY`），其任务运行页/状态展示/日志展示的**交互设计**可在 M5 参考。其 FastAPI 后端与 Agent/Tool Runtime 结构与本项目已自建组件重叠，不采用。

---

## 5. MetaGPT（FoundationAgents/MetaGPT）代码级检查

> 主管令 B-07。目标：寻找可直接适配的独立模块，不引入新编排核心。

| 能力 | 官方实现 | 复用判断 | 决策 |
| -- | -- | -- | -- |
| Role | `metagpt.roles.Role`（带 `_observe/_think/_act` 循环） | Role 生命周期循环与 LangGraph 节点重复 | `REJECT`（编排） |
| Action | `metagpt.actions.Action` | 动作抽象可参考，但 LangGraph 节点更简单 | `DESIGN_REFERENCE_ONLY` |
| ActionNode | `metagpt/actions/action_node.py`（声明式 schema→pydantic→LLM 填充，876 行） | **最高价值独立可适配模块**：结构化输出引擎，零编排耦合；可直接作 Planner/Reviewer 产物 schema 引擎 | `SELECTIVE_CODE_REUSE`（vendor + 保留 MIT 头） |
| Message | `metagpt/schema.py: Message`（~200 行 pydantic + MessageQueue） | 消息协议设计可参考；`RoleMessage` 已不存在（源码确认） | `SELECTIVE_CODE_REUSE`（可选 vendor） |
| Environment | `metagpt.environment.Environment`（subscribe/publish） | 消息总线式环境，与 LangGraph 通道语义重叠 | `REJECT`（避免第二编排语义） |
| SOP | `Serialization / subscription` 路由 | SOP 编排语义由 LangGraph 图承担 | `REJECT`（编排） |
| 标准交付物模板 | `metagpt/actions/write_prd_an.py` 等 `*_an.py` ActionNode 图 | **值得借鉴**：标准交付物模板（PRD/系统设计/任务）是纯 ActionNode 图，无编排 import | `SELECTIVE_CODE_REUSE`（模板 schema 文案） |

**结论**：MetaGPT **不引入编排**。其 **ActionNode 结构化输出引擎**与**标准交付物模板**是独立可适配模块，可作为 M2 Planner/Reviewer 产物 schema 的实现参考（`SELECTIVE_CODE_REUSE`，vendor 时保留 MIT 头并记录 provenance）。Role/Environment/SOP 循环 REJECT。

---

## 6. Microsoft Agent Framework（microsoft/agent-framework）代码级检查

> 主管令 B-07。目标：寻找独立可适配模块，**不引入第二编排核心**。

| 能力 | 官方实现 | 复用判断 | 决策 |
| -- | -- | -- | -- |
| Middleware | `agent_framework.AgentMiddleware/FunctionMiddleware/ChatMiddleware` | 中间件管道思想与 `ToolGateway`/`ModelGateway` 治理层思路相似；叶子拦截机制，无 runner 耦合，但类型绑定框架 Message | `WRAPPER_ADAPTER`（需薄适配层） |
| Workflow | `agent_framework.workflow`（WorkflowApp/WorkflowNode/Executor/Runner） | 与 LangGraph 图重叠 | `REJECT`（第二编排核心） |
| Checkpoint | `agent_framework.CheckpointStorage`（Protocol）/`FileCheckpointStorage` | 自包含持久化叶子；但用 pickle（RestrictedUnpickler 允许列表） | `DIRECT_DEPENDENCY`（可选；与 LangGraph SqliteSaver 二选一） |
| HITL | `agent_framework.hitl`/`ToolApprovalMiddleware`/`UserInputRequiredException` | 工具审批中间件可薄包装到 ToolGateway；workflow 级 HITL 与 LangGraph interrupt 重叠 | `WRAPPER_ADAPTER`（工具审批部分）/`REJECT`（workflow 级） |
| Tracing | `agent_framework.observability`（纯 OpenTelemetry 叶子） | 可包装 ModelGateway 产生 token/usage span | `DIRECT_DEPENDENCY`（M2 可选接入 OTel） |
| Provider Adapter | `agent_framework.openai.OpenAIChatClient/OpenAIChatCompletionClient`（独立 PyPI 包，零编排耦合） | **最干净的直接采纳**：可替换 DeterministicFakeModel 后接真实 OpenAI/Azure | `DIRECT_DEPENDENCY`（M2 Provider 层） |
| 异常治理 | `agent_framework.exceptions`（纯叶子模块，typed 异常层级） | 可标准化本项目 gateway/audit/checkpoint 错误分类 | `DIRECT_DEPENDENCY`（可选采纳） |

**结论**：Microsoft Agent Framework **不引入、不 Fork 编排**。其 Provider 适配（`agent_framework.openai`，零编排耦合）可作为 M2 真实模型 Provider 的直接采纳候选；Tracing（纯 OTel）、异常治理、CheckpointStorage 为可选独立叶子；Middleware 工具审批可薄包装。编排、workflow 级 HITL 均 REJECT（LangGraph/自建已覆盖）。

---

## 7. 当前代码重复度审计（主管令任务 C）

| 当前文件 | 当前职责 | 上游对应实现 | 重复程度 | 决策 | 迁移成本 |
| -- | -- | -- | -- | -- | -- |
| `app/graph.py` | 单节点 StateGraph + checkpoint 版本校验 | `langgraph.graph.StateGraph`（官方） | 0–1 | **KEEP** | 低 |
| `app/runner.py` | 任务装配器：budget/audit/gateway 注入 + SqliteSaver + invoke | `langgraph` `compile()/invoke()`（官方）+ `SqliteSaver` | 1 | **THIN** | 低 |
| `app/core/state.py` | `TaskState` 状态模型 + `TaskStatus/FailureCode` | LangGraph state（pydantic）通道；`TaskStatus` 等为项目特有 | 1 | **THIN**（M2 加 Annotated reducer；TaskStatus 字符串化规避 msgpack 警告） | 中 |
| `app/core/budget.py` | 预算冻结 + 记账（唯一权威） | 无上游对应 | 0 | **KEEP**（差异化治理） | 无 |
| `app/gateway/model_gateway.py` | Provider Protocol + DeterministicFakeModel + 预算记账 | OpenAI-compatible Provider（官方 SDK/端点） | 1 | **THIN**（Provider 层适配真实模型） | 中 |
| `app/gateway/tool_gateway.py` | 工具鉴权/拦截/幂等/审计 | `langgraph.prebuilt.ToolNode`（工具执行） | 2 | **THIN**（治理保留；执行可接 ToolNode） | 中 |
| `app/gateway/audit.py` | JSONL 审计 + 脱敏 | 无上游对应 | 0 | **KEEP**（差异化治理） | 无 |
| `app/tools/spec.py` | `ToolSpec`/`RiskLevel`/`ToolResult` | LangChain `BaseTool`（schema 思路） | 1–2 | **THIN**（M2 可桥接 LangChain/OpenAI tool schema） | 中 |
| `app/api/server.py` | 最小 FastAPI（tasks 创建/查询） | FastAPI 官方（无重复） | 0 | **KEEP**（M2 补 /health、streaming、审批端点） | 低 |

### 7.1 决策原则落实
- **KEEP**（差异化治理，禁止替换）：`budget.py`、`audit.py` —— 权限审批、硬预算、审计证据是项目护城河。
- **THIN**（官方 API 外薄包装）：`runner.py`（装配层）、`tool_gateway.py`（治理在 ToolNode 外层）、`model_gateway.py`（Provider 适配）、`spec.py`（tool schema 桥接）、`state.py`（reducer 升级 + 序列化加固）。
- **REPLACE**：无整文件替换项；LangGraph 已提供的能力（checkpoint/interrupt/Send/streaming）M2 直接使用，不替换现有正确代码。
- **MERGE**：`state.py` 的列表字段（`tool_calls/evidence/approvals`）与 LangGraph `Annotated` reducer 合并，以支持 M2 fan-in 不覆盖状态。
- **DEFER**：`server.py` 的 `/health`、SSE、审批端点、streaming 端点；`tool_gateway` 的 MCP 接入；沙箱执行（M3）。

---

## 8. 顶层结论

1. **编排核心唯一确定为 LangGraph**（已依赖），StateGraph/Checkpoint/interrupt/Send/streaming/RetryPolicy 全部 `DIRECT_DEPENDENCY`，不自研。
2. **治理层（预算、审批、审计、脱敏、幂等）保留为项目自研**，以薄包装方式留在 LangGraph 节点外层。
3. **不引入第二编排核心**：CrewAI Crew/Flow、Microsoft Agent Framework Workflow、OpenAI Agents SDK Runner、MetaGPT Environment/SOP 均 REJECT。
4. **可借鉴/可独立适配的叶子模块**：
   - OpenAI Agents SDK：`function_tool` 工具 schema（DIRECT）、MCP server 包装、sandbox session、Model Provider（WRAPPER_ADAPTER）。
   - MetaGPT：`ActionNode` 结构化输出引擎 + 标准交付物模板（SELECTIVE_CODE_REUSE，vendor 时保留 MIT 头）。
   - Microsoft Agent Framework：`agent_framework.openai` Provider（DIRECT，零编排耦合）、OTel tracing、typed 异常、CheckpointStorage（可选）。
   - CrewAI：Agent/Task/YAML 配置模型、`@tool` 注册模式（设计参考）。
5. **Fork 决策**：ChatDev 前端不 Fork（Vue 3 + Vite，页面单体、与后端协议紧耦合，复用 <20%，仅设计参考）；无任何上游仓库需要长期 Fork 同步。
6. **真实上游缺陷已登记**：LangGraph `Command(resume=None)` bug（`pregel/_loop.py:927`）、msgpack 未注册类型警告；OpenAI Agents SDK 0.x 版本动荡需 pin。

详细组件映射见 `UPSTREAM_COMPONENT_MAP.md`；许可证合规见 `LICENSE_COMPLIANCE.md`；M2 方案见 `docs/planning/M2_REUSE_FIRST_PLAN.md`。
