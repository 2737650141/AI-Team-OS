# Model Gateway 架构（docs/architecture/MODEL_GATEWAY.md）

对应总管令 005 六/七/十/十一。M3-A 实现。

## 1. 定位

Model Gateway 是**预算使用量的唯一权威记账入口**与**模型调用的唯一入口**。
真实模型只能通过 Gateway 产生经 Pydantic Schema 校验的提议（005 3.2），
所有状态变更仍由确定性节点执行。

## 2. 组件

```text
调用方（LLMPlanner/LLMResearcher/LLMReviewer/LLMSupervisorDecision）
    │
    ▼
ModelGateway.generate(request)          ← 唯一入口（app/gateway/model_gateway.py）
    │  1. estimate_usage → 预算预留（10.1）
    │  2. can_call 不足 → BUDGET_INSUFFICIENT，不发起请求（10.4）
    │  3. 重试循环：可重试错误指数退避（11.3），每尝试写审计
    │  4. 成功 → 按实际 Usage 结算（10.2），prompt 哈希入审计（6.2）
    ▼
ModelProvider（Protocol：generate/estimate_usage/health_check）
    ├─ FakeModelProvider            （自动测试基线，离线/无费用/可重复）
    └─ OpenAICompatibleProvider     （真实调用，必须显式开启）
```

## 3. 数据契约

- `ModelRequest`：request_id/task_id/run_id/agent_id/role_type/model/messages/
  response_schema/temperature/max_output_tokens/timeout_seconds/metadata。
  **不含 API Key**（6.1）。
- `ModelResponse`：request_id/provider/model/raw_text/structured_output/tokens/
  estimated_cost/latency_ms/finish_reason/provider_request_id/retry_count。
  raw_text 仅受控调试模式短期保留（6.2）。
- `ProviderError`：code（13 分类）+ safe_message（不含服务端原始响应）+ retryable +
  provider + model + attempt（6.3）。

## 4. 预算三态（10.x）

```text
调用前：estimated（输入 Token 估算 + 最大输出预留 + 最大费用估算）→ can_call 检查
调用后：actual（Provider 返回的真实 Usage）→ budget.record 结算，未用预留自然释放
价格：lookup_price（provider+model 精确匹配）；未知价格 estimated_cost=None，不伪造
失败：BUDGET_INSUFFICIENT → Supervisor 决定降级/停止/请求用户提高预算（LLM 无权）
恢复：BudgetController 以 checkpoint budget_usage 重建（不清零）
```

## 5. 重试（11.x）

- 可重试：rate_limited / timeout / connection_error / provider_internal_error。
- 不可重试：authentication / permission / invalid_request / model_not_found /
  budget_insufficient / config_error / schema_validation_failed / cancelled。
- 指数退避 `min(0.5 * 2^attempt, 8s)`，最大次数集中配置；每尝试写审计；
  重试不重置预算；request_id 跨重试稳定；自动测试注入 sleep_fn（Fake Clock）。

## 6. 结构化输出（9.x）

`generate_structured`（app/gateway/structured_gen.py）：

```text
生成 → JSON 提取（单顶层对象，拒多对象/超大/Schema 外字段）→ Pydantic 校验
     → 失败：保存脱敏错误摘要 → 生成一次修复请求 → 重试（上限集中配置）
     → 超限：SCHEMA_VALIDATION_FAILED，不写正式状态
```

## 7. 审计

每次模型调用记录：provider/model/tokens/estimated_cost/prompt_hash/retry_count/latency_ms。
不记录 messages 全文与 API Key（6.2/5.2）。
