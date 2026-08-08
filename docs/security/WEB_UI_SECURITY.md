# Web UI 安全（010 三十五/四十三）

## 内容安全（XSS）

所有以下内容视为 **UNTRUSTED**：模型输出、Evidence、网页内容、GitHub 内容、
Diff、工具输出、日志。

- **禁止 `dangerouslySetInnerHTML`**（除非经过严格 sanitize——本项目不使用）。
- Markdown/HTML 一律按纯文本渲染（React 默认转义）。
- Diff 按行渲染为独立 `<div>`（`DiffViewer`），不做 HTML 注入。
- URL 只作为文本显示，不自动可点击跳转（避免 `javascript:` 等）。

## Secret

- 前端绝不持久化密钥：无 localStorage / sessionStorage / IndexedDB /
  Cookie / URL 参数 / 错误报告。
- API Key 输入框 `type=password` + `autocomplete=off` + `spellcheck=false`；
  提交成功立即清空组件状态。
- `GET /settings/connections` 与保存响应**绝不**返回 Secret 值/前缀/后缀/last4。
- 事件 / Evidence / Artifact / Audit / Trace 统一经 `redact()` 脱敏。

## SSE payload

- `payload_safe` 逐字段脱敏后才落库/推送。
- 事件 summary 限长 2000 字符；不包含隐藏推理。

## 网络

- 后端默认绑定 `127.0.0.1:8000`；前端 `127.0.0.1:5173`；不监听公网。
- Base URL SSRF 校验：拒绝 localhost/内网/元数据地址；仅本地 Provider
  （Ollama `local_provider=true`）放行 `127.0.0.1:11434`。
- `Test Connection` 失败返回安全映射状态，不回传 Provider 原始错误。

## 前端依赖

- 成熟组件：React / React Router / TanStack Query / Lucide；UI 组件库评估
  shadcn/ui（本轮使用手写轻量样式，未引入）。
- 依赖许可证：React/ReactDOM MIT、React Router MIT、TanStack Query MIT、
  Vite MIT、Lucide ISC、Vitest MIT、Playwright Apache-2.0——均为宽松许可。
