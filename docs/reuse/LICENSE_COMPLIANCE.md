# 许可证与来源合规（LICENSE COMPLIANCE）

> 文档状态：主管令 003，任务 B（许可证合规）
> 审计时间：2026-08-05
> 审计 HEAD：`50e0663`
> 原则（主管令五）：
> 1. 优先依赖包，不复制源码。
> 2. 复制 MIT 代码也必须保留原许可证和版权声明。
> 3. 使用 Apache-2.0 代码必须满足许可证与 NOTICE 要求。
> 4. 禁止无来源复制代码。
> 5. 禁止删除上游版权头。
> 6. 每个选择性复用代码块必须有 provenance 记录。
> 7. 不从未核实许可证的博客、Gist 或二次转载仓库复制代码。

---

## 1. 本项目建设依赖的许可证

| 依赖 | 许可证 | 直接依赖 | 复制源码 | 说明 |
| -- | -- | -- | -- | -- |
| langgraph (1.2.10) | MIT | ✅ | 否 | pip 安装，未复制源码 |
| langgraph-checkpoint-sqlite (3.1.1) | MIT | ✅ | 否 | pip 安装，未复制源码 |
| langgraph-sdk / langgraph-checkpoint（传递） | MIT | ✅（传递） | 否 | — |
| fastapi (0.141.1) | MIT | ✅ | 否 | — |
| uvicorn | BSD-3-Clause | ✅ | 否 | — |
| pydantic (2.13.4) | MIT | ✅ | 否 | — |
| pydantic-settings | MIT | ✅ | 否 | — |

**结论**：建设期所有直接依赖均为 pip 包，**未复制任何源码**，无需 NOTICE。项目未来若开源，建议使用 MIT 或 Apache-2.0，与上述依赖兼容。

---

## 2. 复用审计的候选上游许可证

| 项目 | 仓库 | 许可证 | 是否直接依赖 | 是否复制源码 | 复制文件/行范围 | 原始版权声明 | 我方修改 | 需 NOTICE | 商用+修改 | 与本项目许可证兼容性 |
| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |
| LangGraph | langchain-ai/langgraph | MIT | ✅（已依赖） | 否 | — | — | — | 否 | 允许 | 兼容 |
| OpenAI Agents SDK | openai/openai-agents-python | MIT | ❌（仅参考） | 否 | — | — | — | 否（无复制） | 允许 | 兼容 |
| CrewAI | crewAIInc/crewAI | MIT | ❌ | 否（仅设计参考 YAML/数据模型） | — | — | — | 否 | 允许 | 兼容 |
| ChatDev | OpenBMB/ChatDev | Apache-2.0 | ❌ | 否（不 Fork，不复制） | — | — | — | 否 | 允许 | 兼容 |
| MetaGPT | FoundationAgents/MetaGPT | MIT | ❌ | 否（交付物模板仅参考结构，不复制文案） | — | — | — | 否 | 允许 | 兼容 |
| Microsoft Agent Framework | microsoft/agent-framework | MIT | ❌（仅参考） | 否 | — | — | — | 否 | 允许 | 兼容 |

**核心结论**：**本轮未复制任何上游源码**（决策均为 DIRECT_DEPENDENCY / WRAPPER_ADAPTER / DESIGN_REFERENCE_ONLY / REJECT），
因此 **NOTICE 与版权头要求当前不触发**。全部为依赖包或设计参考。

---

## 3. 选择性复用预防性登记（当前为空，M2 落地时若出现必须登记）

> 规则 6：每个选择性复用代码块必须有 provenance 记录。**本轮（M0-M1 审计）未复制任何上游源码**。
> M2 方案已把以下项列为 **候选 SELECTIVE_CODE_REUSE**，若总管批准采纳，**必须在此登记后再落地**：

| 组件 | 来源 | 许可证 | 复制文件/行 | 原始版权声明 | 修改说明 | 记录日期 |
| -- | -- | -- | -- | -- | -- | -- |
| MetaGPT `ActionNode`（结构化输出引擎） | FoundationAgents/MetaGPT `metagpt/actions/action_node.py` | MIT（Copyright (c) 2024 Chenglin Wu） | （M2 待定） | 保留原 MIT 头 | vendor/精简，注明来源 SHA `11cdf466` | M2 时登记 |
| MetaGPT 标准交付物模板（`*_an.py`） | 同上 | MIT | （M2 待定） | 保留原 MIT 头 | 同上 | M2 时登记 |
| OpenAI Agents SDK `function_tool` schema | openai/openai-agents-python `src/agents/tool.py` | MIT（Copyright (c) 2025 OpenAI） | （M2 待定） | 保留原 MIT 头 | 依赖优先，不复制 | M2 时登记 |
| CrewAI YAML 配置约定 | crewAIInc/crewAI | MIT（Copyright (c) 2025 crewAI, Inc.） | （M2 待定，若格式参考） | 保留版权声明 | 仅格式约定 | M2 时登记 |

> **当前无任何复制**，因此 NOTICE 与版权头要求未触发；上表为 M2 前置登记，避免"先复制后补记"。

---

## 4. 未解决风险

1. **`ai_team_os.egg-info/` 与 `data/`**：不入库（.gitignore 已覆盖 `*.egg-info/` 与 `data/`），但需确认 M2 开源前无泄漏。
2. **依赖版本锁定**：`pyproject.toml` 用范围约束（`langgraph>=1.2,<2.0`），M2 引入真实模型 Provider 时建议 `pip-compile` 锁定，便于审计可复现。
3. **LangGraph 未来 MsgPack 严格化**：`TaskStatus` 等 pydantic 类型需显式登记或字符串化（见 reuse 审计 §1.2）。
4. **本项目许可证未定**：README 无 LICENSE 文件。M2 开放源码前须决定 MIT 或 Apache-2.0，并与全部依赖兼容（当前均为 MIT/BSD/Apache，均兼容）。
5. **无远程仓库**：当前无 origin。推送前须确认仓库归属与开源许可（本轮禁止推送）。

---

## 5. 合规自检清单

- [x] 优先依赖包，不复制源码（全部能力经 pip 依赖或设计参考）
- [x] 无任何无来源复制代码（复制登记表为空）
- [x] 无删除上游版权头行为（未复制任何带版权头代码）
- [x] 未从博客/Gist/二次转载仓库复制代码
- [x] NOTICE 要求当前不触发（无 Apache-2.0 源码复制）
- [x] 所有建设期依赖许可证已记录
