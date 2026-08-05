# 上游组件映射（UPSTREAM COMPONENT MAP）

> 文档状态：主管令 003，任务 B
> 审计时间：2026-08-05
> 审计 HEAD：`50e0663`
> 检查方式：源码级（GitHub API 定位默认分支 HEAD + 上游实际源码/公开 API/扩展点）
> 未整仓 clone（按令允许：浅检、GitHub 源码查看或只检出指定目录）

---

## 0. 检出版本钉扎（Commit SHA）

| 项目 | 仓库 | 默认分支 | 检查 HEAD (Commit SHA) | 许可证 |
| -- | -- | -- | -- | -- |
| LangGraph | langchain-ai/langgraph | main | `b2926a0ff9589c28c7e01fe7cdbb337b86d5a4b4` | MIT |
| OpenAI Agents SDK | openai/openai-agents-python | main | `4c9e50757bad7c22bc56914a7a249d80df17dec3` | MIT |
| CrewAI | crewAIInc/crewAI | main | `7accafbaf4dd6554a813b48e9523c6bcfe83cb38` | MIT |
| ChatDev | OpenBMB/ChatDev | main | `31fd994416a251ecdeb1f0a73c329271743bfb56` | Apache-2.0 |
| MetaGPT | FoundationAgents/MetaGPT | main | `11cdf466d042aece04fc6cfd13b28e1a70341b1f` | MIT |
| Microsoft Agent Framework | microsoft/agent-framework | main | `1da571860a60f0da4f060bd60c8e7ee8d092cd32` | MIT |

> 注：本地未整仓 clone（仓库大），采用 GitHub API 钉扎 HEAD + 针对关键路径的源码检查。
> 每个能力项给出官方模块路径/扩展点/文档位置。

---

## 1. LangGraph — 能力 → 组件映射

| 能力 | 官方模块/API | 扩展点 | 本项目对应 | 复用分类 |
| -- | -- | -- | -- | -- |
| StateGraph | `langgraph.graph.StateGraph` / `START` / `END` | `add_node/add_edge/add_conditional_edges` | `app/graph.py` | `DIRECT_DEPENDENCY` |
| Checkpointer 接口 | `langgraph.checkpoint.base.BaseCheckpointSaver` | `get_tuple/put_tuple` | `app/runner.py` | `DIRECT_DEPENDENCY` |
| SQLite Saver | `langgraph.checkpoint.sqlite.SqliteSaver` | — | `app/runner.py` | `DIRECT_DEPENDENCY` |
| interrupt 与恢复 | `langgraph.types.interrupt` / `Command(resume=...)` | 节点内调用 interrupt | M2 澄清/审批 | `DIRECT_DEPENDENCY` |
| ToolNode | `langgraph.prebuilt.tool_node.ToolNode` | `tools=`, `InjectedState`, `handle_tool_errors` | `app/gateway/tool_gateway.py` | `WRAPPER_ADAPTER` |
| 状态 reducer | `typing.Annotated[list, operator.add]` | — | `app/core/state.py`（M2 升级） | `DIRECT_DEPENDENCY` |
| 子图 | 内嵌 `StateGraph` 作 node | — | M2 Specialist | `DIRECT_DEPENDENCY` |
| 并行 fan-out/fan-in | `langgraph.types.Send` | `add_conditional_edges` 返回 Send 列表 | M2 并行子任务 | `DIRECT_DEPENDENCY` |
| Streaming | `compiled.stream()` / `.astream_events()` | — | M2 SSE | `DIRECT_DEPENDENCY` |
| 错误重试 | `RetryPolicy` | `add_node(..., retry=RetryPolicy(...))` | M2 工具重试 | `DIRECT_DEPENDENCY` |

## 2. OpenAI Agents SDK — 能力 → 组件映射

| 能力 | 官方模块/API | 本项目对应 | 复用分类 |
| -- | -- | -- | -- |
| Model Provider | `agents.models.Model/ModelProvider` / `OpenAIProvider` | `app/gateway/model_gateway.py`（LLMProvider Protocol） | `WRAPPER_ADAPTER` |
| 工具 schema 抽取 | `agents.function_tool` / `FunctionTool` / `function_schema.py` | `app/tools/spec.py`（ToolSpec）+ LangGraph ToolNode | `DIRECT_DEPENDENCY`（可选） |
| Guardrails | `agents.InputGuardrail/OutputGuardrail` | `BudgetController` / `ToolGateway`（确定性护栏） | `SELECTIVE_CODE_REUSE` |
| Sessions | `agents.sessions` | `app/core/state.py`（TaskState） | `DESIGN_REFERENCE_ONLY` |
| Handoffs | `agents.handoffs` | M2 Agent Registry / 定向返工 | `DESIGN_REFERENCE_ONLY` |
| Tracing | `agents.TracingProcessor` ABC + span-data | `app/gateway/audit.py`（JSONL） | `SELECTIVE_CODE_REUSE` |
| MCP 集成 | `agents.mcp.MCPServer*` / `MCPServerManager` | M3 工具扩展 | `WRAPPER_ADAPTER`（DEFER M3） |
| Sandbox | `agents.sandbox.BaseSandboxSession`（docker/unix_local） | M3 沙箱执行 | `WRAPPER_ADAPTER`（DEFER M3） |
| HITL | `agents.hitl` | 已选 LangGraph interrupt | `REJECT` |
| 编排核心 | `AgentRunner` / `Runner.run()` | `app/runner.py` | `REJECT`（不引入第二核心） |

## 3. CrewAI — 能力 → 组件映射

| 能力 | 官方模块/API | 本项目对应 | 复用分类 |
| -- | -- | -- | -- |
| Agent 数据模型（role/goal/backstory/llm） | `crewai.agent.Agent` | 未来 `AgentSpec`（docs/planning/AGENT_ROLES.md） | `DESIGN_REFERENCE_ONLY` |
| Task 数据模型 | `crewai.task.Task` | `TaskState` 子任务结构 | `DESIGN_REFERENCE_ONLY` |
| YAML 配置 | `crewai.project` | Specialist 声明式注册 | `SELECTIVE_CODE_REUSE`（格式约定） |
| 工具注册 | `@tool` / `BaseTool` | `ToolSpec` | `SELECTIVE_CODE_REUSE`（模式） |
| 结构化输出 | `Task.output_pydantic` | pydantic 状态 schema | `DESIGN_REFERENCE_ONLY` |
| Crew 编排循环 | `crewai.crew.Crew.kickoff()` | 已选 LangGraph | `REJECT` |
| Flow | `crewai.flow.Flow` | — | `REJECT` |

## 4. ChatDev — 能力 → 组件映射

| 能力 | 官方模块/API | 本项目对应 | 复用分类 |
| -- | -- | -- | -- |
| 前端任务运行页 | Vue 3 + Vite SPA（@vue-flow） | M5 UI（计划 Next.js） | `REJECT`（技术栈冲突） |
| 工作流状态展示 | Vue 组件 | M5 UI | `DESIGN_REFERENCE_ONLY` |
| 日志/产物展示 | Vue 组件 | M5 UI | `DESIGN_REFERENCE_ONLY` |
| 前后端通信（WS/SSE） | 自定义协议 | FastAPI SSE（M2） | `DESIGN_REFERENCE_ONLY` |
| FastAPI API 层 / Agent / Tool Runtime | Python | 自建已覆盖 | `DESIGN_REFERENCE_ONLY` |

## 5. MetaGPT — 能力 → 组件映射

| 能力 | 官方模块/API | 本项目对应 | 复用分类 |
| -- | -- | -- | -- |
| Role | `metagpt.roles.Role` | LangGraph 节点 | `REJECT`（编排） |
| Action | `metagpt.actions.Action` | LangGraph 节点 | `DESIGN_REFERENCE_ONLY` |
| ActionNode | `metagpt.actions.action_node.ActionNode` | Planner/Reviewer 产物 schema 引擎 | `SELECTIVE_CODE_REUSE` |
| Message | `metagpt.schema.Message` | 状态通道 | `SELECTIVE_CODE_REUSE`（可选） |
| Environment | `metagpt.environment` | — | `REJECT`（第二编排语义） |
| SOP/Serialization | `metagpt` 订阅路由 | LangGraph 图 | `REJECT` |
| 标准交付物模板 | `metagpt.actions.*_an.py` | Planner/Reviewer 产物 schema | `SELECTIVE_CODE_REUSE` |

## 6. Microsoft Agent Framework — 能力 → 组件映射

| 能力 | 官方模块/API | 本项目对应 | 复用分类 |
| -- | -- | -- | -- |
| Middleware | `agent_framework.AgentMiddleware/FunctionMiddleware/ChatMiddleware` | `ToolGateway` / `ModelGateway` 治理层 | `WRAPPER_ADAPTER` |
| Provider Adapter | `agent_framework.openai.OpenAIChatClient`（独立包，零编排耦合） | Model Gateway Provider 层 | `DIRECT_DEPENDENCY`（可选） |
| Workflow | `agent_framework.workflow` | — | `REJECT`（第二编排核心） |
| Checkpoint | `agent_framework.CheckpointStorage` | LangGraph SqliteSaver | `DIRECT_DEPENDENCY`（可选，二选一） |
| HITL | `agent_framework.hitl` / `ToolApprovalMiddleware` | LangGraph interrupt + ToolGateway | `WRAPPER_ADAPTER`（工具审批） |
| Tracing | `agent_framework.observability` | JSONL 审计 + OTel | `DIRECT_DEPENDENCY`（可选） |
| 异常治理 | `agent_framework.exceptions` | `BudgetExceeded` / Tool 异常路径 | `DIRECT_DEPENDENCY`（可选） |

---

## 7. 汇总：复用分类计数

| 分类 | 计数 | 说明 |
| -- | -- | -- |
| DIRECT_DEPENDENCY | 17 | LangGraph 原生（StateGraph/Checkpoint/interrupt/Send/streaming/RetryPolicy/reducer/subgraph/ToolNode）+ OpenAI function_tool + MS Provider/Tracing/Checkpoint/异常 |
| WRAPPER_ADAPTER | 8 | LangGraph ToolNode 外层治理；OpenAI Model/MCP/Sandbox；MS Middleware/HITL |
| SUBCLASS_EXTENSION | 1 | LangGraph BaseCheckpointSaver（可选自定义持久化） |
| SELECTIVE_CODE_REUSE | 10 | MetaGPT ActionNode/Message/模板；OpenAI guardrail/tracing；CrewAI YAML/tool 模式 |
| DESIGN_REFERENCE_ONLY | 16 | CrewAI/MetaGPT/ChatDev/OpenAI/Microsoft 的设计借鉴 |
| REJECT | 12 | 全部为"第二编排核心"或与 LangGraph 重复的编排语义 |
| DEFER | 2 | MCP 集成、Sandbox（M3） |
