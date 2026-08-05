# ADR-0004：FakeModelProvider 保持自动测试基线

- 状态：已接受（M3-A）
- 日期：2026-08-05
- 关联：docs/operations/REAL_MODEL_SETUP.md、tests/test_m3_governance.py

## 背景

M3-A 接入真实模型后，自动测试面临"真实调用不可重复、有费用、需 API Key"的风险。
005 3.3 明确：自动测试必须使用 DeterministicFakeModel，不调用真实网络、不要求 Key、
可完全重复、无费用；真实模型仅用于 manual integration test，不得成为 CI 必过条件。

## 决策

- `FakeModelProvider`（app/gateway/fake_provider.py）实现完整生产契约
  （generate/estimate_usage/health_check），并保留 `chat()` 兼容 M1 DeterministicFakeModel。
- 全部 pytest 默认 model_mode=fake；真实调用路径仅由 `AI_TEAM_MODEL_ENABLE_REAL=true` 启用。
- 真实手动测试单独标记（`tests/manual/`），不混入普通 pytest；无凭据时标记
  `BLOCKED_BY_CREDENTIALS`，不伪造成功（005 十九）。

## 影响

- 好处：测试确定性/零费用/离线可重复；真实接入风险隔离。
- 代价：真实模型特有的输出分布（长尾幻觉、格式漂移）在自动测试中不体现——
  由手动集成测试补足。
