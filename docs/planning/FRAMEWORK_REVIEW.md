# 开源轮子复核（P0-02）

> 复核日期：2026-08-04
> 复核方法：GitHub 官方仓库元数据（API）、官方 README、PyPI 元数据（`requires_python`、许可证、版本节奏）。结论基于官方一手信息，不依据 Star 数判断。

## 1. LangGraph（langchain-ai/langgraph）

| 项目 | 信息 |
| -- | -- |
| 许可证 | MIT（PyPI 验证） |
| Python 要求 | `>=3.10`（PyPI 验证），当前版本 v1.2.10（2026-07-28 发布） |
| 活跃度 | 38.9k stars；最后 push 2026-08-02；1.0 稳定版于 2025-10 发布，此后每月多次发版（1.2.x 系列） |
| 定位 | 低层编排框架：构建有状态、长运行智能体的基础设施 |

重点能力（官方 README/文档）：
- **Durable execution**：跨失败持久化，可从断点精确恢复（Checkpoint 支持 SQLite / PostgreSQL / Redis 后端）。
- **Human-in-the-loop**：原生 `interrupt` 机制，可在任意节点暂停、检查、修改状态后继续。
- **Memory**：短时工作记忆 + 跨会话长期记忆。
- **Streaming / 子图 / 并行分支**：图模型原生支持。
- 可独立于 LangChain 使用；LangSmith 为可选 SaaS（默认不依赖）。
- 生态提供 Deep Agents（高层包，可参考其实现思想）。

**评估**：作为长期核心依赖合理。1.x 已稳定，许可证友好，持久化与 HITL 恰好是本项目两大核心需求的原生能力。缺点是低层 API 需要自行构建高层抽象（角色、任务、预算治理），这正是本项目要自己写的部分。

## 2. CrewAI（crewAIInc/crewAI）

| 项目 | 信息 |
| -- | -- |
| 许可证 | MIT |
| Python 要求 | `>=3.10, <3.14`（官方 README 验证） |
| 活跃度 | 56.6k stars；最后 push 2026-08-04；发版频繁 |
| 定位 | 高层多智能体编排：Crews（角色代理自主协作）+ Flows（事件驱动精确控制） |

重点能力：Role/Goal/Task 抽象、顺序/层级/并行流程、HITL（Human input on execution）、记忆、checkpointing、多 LLM 连接（含 Ollama 本地模型）、MCP 工具接入（crewai-tools 生态）。

**评估**：产品概念（Role/Goal/Task）正是本项目要借鉴的；但作为核心依赖有顾虑：
- 自带匿名遥测（可关闭，但默认开启）；
- 编排行为封装较深，细粒度状态治理（预算、审批、证据链）需绕开高层 API 才能定制；
- 控制平面/AMP Suite 为商业产品，与"自建治理层"的路线冲突。
**结论：借鉴概念，不作为核心依赖。**

## 3. MetaGPT（FoundationAgents/MetaGPT）

| 项目 | 信息 |
| -- | -- |
| 许可证 | MIT |
| 活跃度 | 69.7k stars；最后 push 2026-01-21（约 6 个月未更新，活跃度下降）；PyPI 有 metagpt 包 |
| 定位 | SOP 驱动的多智能体"软件公司"框架：角色职责 + 标准交付物（PRD/设计/代码/测试） |

**评估**：思想价值高（SOP、角色分工、标准交付物），但工程形态偏研究型、更新放缓，作为长期核心依赖风险高。**结论：只借鉴 SOP 与角色分工思想，不直接依赖。**

## 4. ChatDev（OpenBMB/ChatDev）

| 项目 | 信息 |
| -- | -- |
| 许可证 | Apache-2.0 |
| 活跃度 | 33.9k stars；最后 push 2026-07-24（ChatDev 2.0，活跃） |
| 定位 | LLM 驱动的多智能体协作开发完整应用（含可视化界面） |

**评估**：整体是面向"开发软件"的完整应用而非可嵌入框架；对我们可复用的是**工作流展示与运行界面**的设计思路（阶段流水线 + 可视化工况）。**结论：只借鉴界面与工作流展示思想，不直接依赖。**

## 5. OpenAI Agents SDK（openai/openai-agents-python）

| 项目 | 信息 |
| -- | -- |
| 许可证 | MIT |
| Python 要求 | `>=3.10`（PyPI 验证），当前 v0.19.3（2026-08-04 发布） |
| 活跃度 | 28.4k stars；最后 push 2026-08-04；发版极频繁（0.17→0.19 一个月内多次） |
| 定位 | 轻量多智能体工作流框架；官方声明 provider-agnostic（OpenAI Responses/Chat Completions + 100+ LLM via LiteLLM/any-llm） |

重点能力：Handoffs（交接）、Guardrails（输入/输出护栏）、HITL 内置、Sessions（会话持久化，可选 SQLAlchemy/Redis/MongoDB 后端）、Tracing 内置、**MCP 原生工具接入**、Sandbox agents（Docker 沙箱客户端）、Agents-as-tools。

**评估**：思想非常契合（Guardrail/Handoff/Tracing 正是本项目要借鉴的），工具与模型适配层设计优秀。但作为核心依赖的顾虑：
- 版本仍为 0.x，API 迭代快（本项目是长期项目，核心依赖需稳定）；
- 持久化执行（checkpoint/断点恢复/时间旅行）能力弱于 LangGraph，长任务暂停恢复需自行实现。
**结论：借鉴 Guardrail/Handoff/Tracing 与 Provider 适配思想；不作为编排核心。**

## 6. Microsoft Agent Framework（microsoft/agent-framework）

| 项目 | 信息 |
| -- | -- |
| 许可证 | MIT |
| 活跃度 | 12.6k stars；最后 push 2026-08-04；2025-04 创建（较年轻） |
| 定位 | Python + .NET 双语言生产级多智能体框架 |

重点能力：图工作流（sequential/concurrent/handoff/group）、checkpointing、streaming、HITL、time-travel、**中间件系统**（请求/响应处理、异常处理、自定义管道）、内置 OpenTelemetry、声明式 YAML Agent、多 provider（Azure OpenAI/OpenAI/Foundry/Copilot SDK）。

**评估**：中间件与治理思想值得借鉴；但项目年轻、与微软生态（Foundry/Azure）绑定倾向明显，且 Python 侧 1.0 生态仍在成形。**结论：借鉴中间件与治理思想，不作为核心依赖。**

---

## 复用矩阵

| 能力 | 推荐来源 | 复用方式 | 是否直接依赖 | 替代方案 | 风险 |
| -- | -- | -- | -- | -- | -- |
| 编排核心（状态图/持久化执行/HITL） | LangGraph | 直接使用 StateGraph + Checkpointer | **是** | OpenAI Agents SDK（0.x 不稳）；自研（成本高） | 低层 API，需自建高层抽象 |
| 角色/目标/任务概念 | CrewAI | 借鉴 Role/Goal/Task 抽象为 AgentRole/Subtask 模型 | 否 | 自研（按 AGENT_ROLES.md） | 无（纯设计借鉴） |
| Guardrail/Handoff/Tracing 思想 | OpenAI Agents SDK | 借鉴为 PromptGuardrail + 交接协议 + 结构化运行日志 | 否 | 自研护栏层 | 需在 M1/M2 固化接口 |
| 中间件/治理管道 | Microsoft Agent Framework | 借鉴中间件链模式（请求→治理→执行→响应） | 否 | 自研中间件 | 过度设计风险，MVP 从简 |
| SOP/标准交付物 | MetaGPT | 借鉴角色 SOP 与交付物模板 | 否 | 自研 SOP 模板 | 模板僵化 |
| 工作流可视化界面 | ChatDev | 借鉴运行界面与阶段展示设计 | 否 | 自研控制台（M5） | UI 过度投入 |
| 工具协议 | MCP（官方 SDK） | 直接使用 `mcp` Python SDK 做 MCP 客户端 | **是** | 全自研协议（重复造轮子） | MCP 规范演进，需锁版本 |
| 模型适配 | OpenAI-compatible Provider Adapter | 自研统一接口 + LiteLLM 可选 | 部分（LiteLLM 可选） | 直接用 LiteLLM | 供应商差异需测试矩阵覆盖 |
| Checkpoint 存储 | langgraph-checkpoint-sqlite / -postgres | 直接使用官方适配器 | **是** | 自研状态存储（重复造轮子） | 与 LangGraph 版本绑定 |
| 追踪 | OpenTelemetry（预留） | 结构化日志先行，OTel 接口预留 | 暂不（M5+） | 自研 JSONL 日志 | 预留不足后期改造 |

## 核心结论

1. **LangGraph 为唯一编排核心**，其余框架一律只借鉴思想，不并列引入——符合总管令"禁止多编排核心"的要求。
2. LangGraph 的 durable execution 与原生 HITL 是本项目"长任务暂停恢复"与"人工审批"两条关键需求的直接答案，选型成立。
3. 复用风险集中在 LangGraph 版本升级（1.x 内 minor 兼容良好，需锁 `~=1.2` 并在 CI 做升级回归）与 MCP 规范演进（锁 SDK 版本 + 适配器隔离）。
