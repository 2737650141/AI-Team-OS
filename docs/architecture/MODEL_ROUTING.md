# 模型路由（docs/architecture/MODEL_ROUTING.md）

对应总管令 005 八/十二。M3-A 实现。

## 1. 原则

- 模型路由由**确定性配置**决定，角色不能自行选择模型（8.1）。
- 任务级覆盖来自用户/API 配置，经 `allowed_models` 白名单校验，写入审计（8.2）。
- 模型名称不能注入任意 Provider URL（路由只产出模型名，URL 由 Provider 配置决定）。
- fallback 由 ModelRouter 确定性执行，模型不可自行调用备用模型（12.1）。

## 2. 角色默认策略（8.1）

| 角色 | 默认策略 | 配置键 |
| --- | --- | --- |
| Supervisor | 强推理、较低温度 | `AI_TEAM_MODEL_SUPERVISOR` |
| Planner | 强推理、结构化输出 | `AI_TEAM_MODEL_PLANNER` |
| Researcher | 中等成本、证据优先 | `AI_TEAM_MODEL_RESEARCHER` |
| Reviewer | 与执行角色隔离，可用不同模型 | `AI_TEAM_MODEL_REVIEWER` |
| Executor | 代码/操作专用，M3-C 后启用 | `AI_TEAM_MODEL_EXECUTOR` |

未配置角色模型时继承 `AI_TEAM_MODEL_DEFAULT`。

## 3. 覆盖与校验（8.2）

```python
router.resolve("planner", overrides={"planner": "p-model"})  # 白名单通过
router.resolve("planner", overrides={"planner": "evil"})     # ValueError: override rejected
```

覆盖来源仅限用户/API 配置（CLI `--model-override ROLE=MODEL`、API `model_overrides`），
不由 LLM 输出决定；每次覆盖写 `model_override` 审计事件。

## 4. Reviewer 隔离（8.3）

- 默认建议 `reviewer.model != researcher.model`（`reviewer_isolated()` 可判定），非强制。
- 同一模型时仍保持：Prompt 隔离、上下文隔离（ContextBuilder 独立契约）、
  不传执行者隐藏推理、确定性审查优先、Reviewer 无权覆盖确定性失败。

## 5. 降级（12.x）

```text
fallback_models 配置（AI_TEAM_MODEL_* 或路由配置）→ router.fallback(role, model)
降级条件：连续超时 / 限流 / 模型不可用 / 上下文超长 / （用户允许时）预算不足换廉价模型
禁止静默降级：审计 model_fallback 事件记录 from/to/原因；最终结果说明降级与质量影响
API Key 错误不得自动尝试未知 Provider
```
