# PRODUCT-01 REAL GATE 报告（020-B）

- 执行时间: 2026-08-12 17:42:15
- provider: DeepSeek Official / 
- 费用上限: max_real_requests=150, max_total_tokens=300000, max_wall_time=1800s

## STANDARD: 0/2（门禁 ≥9）→ FAIL

| id | status | failure | complexity | roles | calls | tools | tokens | rework | replan | latency_s |
|---|---|---|---|---|---|---|---|---|---|---|
| T01 | failed | budget_exceeded | standard | - | 81 | 18 | 94686.0 | 0 | 0 | 104.0 |
| T02 | failed | rework_limit_exceeded | standard | researcher | 76 | 14 | 92123.0 | 3 | 2 | 98.3 |

- 全编排样本（真实 Supervisor/Planner/Researcher/Executor|Reviewer）: 0

- 总模型调用: 157（上限 150）
- 总 tokens: 186809.0（REPORTED，上限 300000）
- 总耗时: 202.3s

## STATUS: PRODUCT_BASELINE_PARTIAL