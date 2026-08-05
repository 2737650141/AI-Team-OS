# ADR-0003：OpenAI-compatible Provider 作为第一版真实模型协议

- 状态：已接受（M3-A）
- 日期：2026-08-05
- 关联：docs/architecture/MODEL_GATEWAY.md、docs/security/MODEL_PROVIDER_SECURITY.md

## 背景

M3-A 需要接入真实模型，候选协议有 Chat Completions 兼容与 Responses 兼容两类。
005 7.1 要求优先选择一种稳定 API 形态作为当前标准，不同时实现两套未经测试的协议。

## 决策

采用 **Chat Completions 兼容**作为第一版协议（`OpenAICompatibleProvider`）：

- 兼容 OpenAI 官方兼容接口、常见中转 API、DeepSeek 等兼容端点。
- 后续 Ollama 兼容端点通过独立本地模式开关接入（`allow_local`，默认 False）。
- Responses 兼容协议在至少一个真实端点实测后另行评估（不并行维护两套）。

## 影响

- 好处：生态最广（几乎所有中转/自托管都提供 chat/completions）；实现单一、可充分测试。
- 代价：Responses 特性（如内置工具协议）暂不可用；后续如需迁移由新 ADR 决定。
- 安全约束（7.2/7.3/7.4）：仅 https、SSRF 校验、真实调用必须显式开启。
