# M2 二次开发方案：复用优先（REUSE-FIRST PLAN）

> 文档状态：主管令 003，任务 D — 提交总管批准，**批准前禁止修改内核**
> 审计 HEAD：`50e0663`
> 方案原则（主管令六）：
> **优先使用官方能力 → 在官方能力外包治理层 → 只有缺口才自研**

---

## 0. 架构决策基线

| 决策 | 结论 | 理由 |
| -- | -- | -- |
| 编排核心 | **LangGraph（唯一）** | 已依赖 1.2.10；StateGraph/Checkpoint/interrupt/Send/streaming 全原生 |
| 第二编排核心 | **禁止**（CrewAI / MS Agent Framework / OpenAI Agents SDK 编排语义） | 架构铁律；避免双编排状态/上下文撕裂 |
| 治理层 | **项目自研，留在 LangGraph 节点外层** | 预算、审批、审计、脱敏、幂等必须确定性；LLM 不拥有安全决策权 |
| Provider | Model Gateway 薄适配 OpenAI-compatible（或官方 openai SDK） | M1 的 LLMProvider Protocol 保留，换真实 provider |

---

## 1. 保留组件（KEEP，不动）

| 组件 | 原因 |
| -- | -- |
| `app/core/budget.py`（BudgetController） | 硬预算冻结 + 唯一权威记账，项目差异化能力，无上游替代 |
| `app/gateway/audit.py`（AuditLog + redact） | JSONL 证据链 + 密钥脱敏，项目差异化能力 |
| `app/tools/spec.py`（ToolSpec/RiskLevel/ToolResult） | 风险分级 + 只读/审批标注，是治理的前提 |
| `app/gateway/tool_gateway.py` 的**治理逻辑** | 鉴权、拦截、幂等、审计、审批 pending 生成，全部保留 |
| `app/core/state.py` 的 `TaskStatus/FailureCode/Evidence/Approval/ToolCallRecord` | 统一状态枚举与证据模型，项目特有 |
| 所有现有测试 | 禁止删除；作为 M2 回归基线 |

## 2. 变薄组件（THIN，官方 API 外的薄包装）

| 组件 | 变薄方式 |
| -- | -- |
| `app/runner.py` | 保留装配职责（budget/audit/gateway 注入 + SqliteSaver + invoke），但 M2 改用官方 `interrupt()`/`Command(resume=...)` 做澄清/审批恢复，去掉自定义恢复逻辑（当前也无） |
| `app/gateway/model_gateway.py` | Provider 层换真实 OpenAI-compatible 适配（保留 `LLMProvider` Protocol + 预算记账 + audit）；`DeterministicFakeModel` 保留为测试/降级场景 |
| `app/gateway/tool_gateway.py` 的**执行层** | M2 可桥接 `langgraph.prebuilt.ToolNode` 承担工具执行与错误处理；`ToolGateway` 作为**前置治理代理**（在 ToolNode 之前鉴权/拦截/幂等，通过 `InjectedState` 或预处理器接入） |
| `app/core/state.py` 的列表字段 | `tool_calls/evidence/approvals` 改为 `Annotated[list, operator.add]` reducer，支持 M2 并行子任务 fan-in 不覆盖 |
| `app/api/server.py` | 补 `/health`（探活）、SSE 流式、任务查询/审批端点；仍为薄 FastAPI 层 |

## 3. 替换组件（REPLACE，上游组件替换自研）

> 原则：**LangGraph 已提供的执行与恢复能力优先直接使用**。当前 M1 无整文件"错误自研"需替换，但以下自研/未实现项 M2 用官方能力替代：

| 自研/缺口 | 替换为官方能力 |
| -- | -- |
| （未来）自定义恢复逻辑 | LangGraph `interrupt()` + `Command(resume=...)`（原生 HITL/澄清/审批暂停） |
| （未来）自定义并行子任务 | LangGraph `Send` API fan-out/fan-in |
| （未来）自定义重试 | LangGraph `RetryPolicy`（工具/节点级） |
| （未来）自定义消息流 | LangGraph `compiled.stream()` / `.astream_events()` → SSE |
| （当前）`app/graph.py` 手写节点装配 | 继续用官方 `StateGraph.add_node/add_edge`；M2 拆 Supervisor/Planner/Researcher/Reviewer 子图 |

## 4. 新增组件（仅 M2 真正缺失）

> 不得把 LangGraph 已提供的能力列为自研组件。以下为 M2 实际需自研/组装的能力：

| 组件 | 说明 | 是否自研 |
| -- | -- | -- |
| Supervisor | 总控节点：意图理解、任务状态机推进、派发、降级 | **自研节点**（编排用官方图） |
| Planner | 拆分子任务 + `subtask_budget_allocations`（受 BudgetController 冻结规则约束） | **自研节点** |
| Researcher | 调研/采集（用只读工具 + Fixture/证据） | **自研节点**（复用 ToolGateway 治理） |
| Reviewer | 双轨评审：证据校验 + 产物质量；产出 pass/reject | **自研节点** |
| Agent Registry | 角色/工具/Specialist 注册表（声明式） | **自研模块** |
| Plan Schema | 计划/子任务/里程碑的 pydantic schema（承接 `subtask_budget_allocations`） | **自研模块** |
| 定向返工 | Supervisor 依据 Reviewer 驳回仅重派相关子任务 | **自研编排逻辑**（用官方子图/Send） |
| 并行 fan-out/fan-in | 用官方 `Send` + reducer 合并 | **用官方能力**（不自研） |
| 澄清 interrupt | 需求不明确时 Supervisor 节点 `interrupt()` 暂停 + SSE 推送问题 | **用官方能力**（不自研） |

**明确不自研**（LangGraph 已提供）：checkpoint 持久化、interrupt/resume 语义、Send 并行、streaming、RetryPolicy、状态 reducer、子图。

## 5. Fork 决策（主管令 6.5）

| 问题 | 明确回答 |
| -- | -- |
| 是否 Fork ChatDev | **否**。前端为 Vue 3 + Vite SPA（页面单体、与后端 WS 协议紧耦合），复用 <20%，仅设计参考（任务运行页/状态展示交互与信息架构）。后端结构自建已覆盖。 |
| 是否 Fork CrewAI | **否**。仅借鉴 Agent/Task 数据模型与 YAML 配置约定（设计参考）。编排循环与 Flow REJECT。 |
| 是否 Fork MetaGPT | **否**。仅 `ActionNode` 结构化输出引擎 + 标准交付物模板可 `SELECTIVE_CODE_REUSE`（vendor 时保留 MIT 头 + provenance）。Role/Environment/SOP REJECT。 |
| 是否直接依赖 OpenAI Agents SDK | **否（整体）**。仅其 `function_tool`（工具 schema）与 `Model/ModelProvider`（Provider 适配）可薄采纳；Runner/Agent 编排语义 REJECT。接入真实模型优先用官方 `openai` SDK 或 OpenAI-compatible HTTP。 |
| 是否以 Microsoft Agent Framework 作 Provider | **可选**：其 `agent_framework.openai` 是独立 PyPI 包（零编排耦合），可作为 M2 真实 Provider 备选；编排/Workflow/HITL REJECT。 |
| 是否只以 LangGraph 为编排核心 | **是**。唯一编排核心。 |
| 哪些上游仓库未来需长期同步 | **无 Fork、无复制 → 无长期同步负担**。仅需跟进 LangGraph/checkpoint-sqlite 小版本（依赖升级）。若 M2 采纳 MetaGPT ActionNode 或 OpenAI function_tool（vendor/依赖），按 §6 登记。 |

## 6. 上游同步策略（主管令 6.6）

> 因无 Fork / 无选择性复制，无 upstream remote、无跟踪分支、无冲突合并需求。

| 项 | 策略 |
| -- | -- |
| upstream remote | 不配置（无 Fork） |
| 跟踪分支/标签 | LangGraph 依赖按 `>=1.2,<2.0` 范围；M2 建议 `pip-compile` 锁定精确版本 |
| 升级周期 | 跟随 LangGraph 小版本；升级前跑全量 pytest + 黄金任务 |
| 冲突处理 | 无（无代码复制） |
| 回归测试 | CI 已含 ruff/mypy/pytest；M2 增加黄金任务评测 |
| 许可证检查 | 升级后核对依赖许可证（当前全 MIT/BSD/Apache 兼容） |
| 自定义改动隔离 | LangGraph 全部通过官方 API 使用，无 vendor 补丁；**例外**：`Command(resume=None)` 上游 bug 需规避（传实际值），登记到风险表 |

### 6.1 上游风险登记
| 风险 | 缓解 |
| -- | -- |
| LangGraph 1.2.10 `Command(resume=None)` UnboundLocalError（`pregel/_loop.py:927`） | 恢复一律传 `Command(resume=<实际值>)`；登记为上游 bug，升级时验证是否修复 |
| msgpack 未注册类型 `TaskStatus` 反序列化警告（未来硬错误） | M2 编译图时显式 `allowed_msgpack_modules`，或将 `TaskStatus` 状态通道字符串化 |
| StarletteDeprecationWarning（httpx→httpx2） | 依赖升级期处理；不影响 M1 |

---

## 7. M2 交付验收（建议，供总管批准）

1. `pytest` 全绿（现有 22 项 + M2 新增 Supervisor/Planner/Reviewer/并行/澄清用例）。
2. 黄金任务 **GT-01/02/03/07/09/11/12** 至少核心链路通过（GT-01/03/10/11 必须通过）。
3. `interrupt()` 澄清 + `Command(resume)` 恢复：一次真实 CLI/API 演示（复用 A-04 方法论）。
4. 并行 fan-out/fan-in：`Send` + reducer 合并，状态无覆盖（STATE_MODEL 校验）。
5. `ruff check` / `ruff format` 收尾（修正 budget.py/state.py/test_audit.py 格式差异）。
6. 真实 Model Provider 接入（或保留 Fake 但通过 Provider 接口）。
7. **全程不 push**，等待总管批准后再动内核。
