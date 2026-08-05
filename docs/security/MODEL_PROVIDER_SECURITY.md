# Model Provider 安全（docs/security/MODEL_PROVIDER_SECURITY.md）

对应总管令 005 5.2/7.2/7.3/7.4/二十。M3-A 实现。

## 1. API Key 规则（5.2）

API Key：
- 只从环境变量 `AI_TEAM_MODEL_API_KEY` 读取（显式禁用 .env 文件加载）。
- 不进入 RuntimeState / Checkpoint / messages / 审计日志 / 异常信息 / API 响应 / trace。
- Agent 不可读取；仅存在于 `OpenAICompatibleProvider._api_key` 私有字段。
- `.env.example` 只含占位符。

测试强制：`test_api_key_not_in_audit_or_messages`、`test_api_schema_has_no_api_key_field`、
`test_authorization_header_not_logged`（tests/test_m3_governance.py、test_m3_openai_provider.py）。

## 2. HTTP 客户端（7.2）

- 明确连接/读取超时（`AI_TEAM_MODEL_TIMEOUT_SECONDS`，默认 60s）。
- 最大响应体限制（1MB，`max_read_bytes`）。
- TLS 验证默认开启（httpx 默认）。
- 禁止自动跟随重定向（follow_redirects=False，3xx 手动校验后拒绝）。
- 可取消（httpx 原生）、连接复用（Client 复用）、User-Agent 标识（ai-team-os/0.3.0）。
- 不记录 Authorization 头。

## 3. Base URL SSRF 防护（7.3）

`_blocked_host_reason` 拒绝：
- localhost / 127.0.0.1 / ::1（环回）。
- RFC1918 内网（10.x / 172.16-31.x / 192.168.x）。
- 链路本地 / 保留 / 组播地址。
- 云元数据（169.254.169.254、metadata.google.internal、*.internal）。
- 域名先解析再判定（DNS 解析属 SSRF 防护一部分）。

仅允许 `https://`；本地 Ollama 模式需独立开关（`allow_local`，默认 False）。
重定向目标地址再次校验（`test_redirect_to_internal_rejected`）。
测试环境用依赖注入 mock transport（httpx.MockTransport），不放宽生产校验。

## 4. 真实调用开关（7.4）

`AI_TEAM_MODEL_ENABLE_REAL=true` 才允许真实调用；否则 Provider 返回确定性
CONFIG_ERROR（"real model calls disabled"），不得静默调用。

## 5. 安全边界（005 二十）

本阶段继续禁止：真实 GitHub / Web Search / MCP / 文件写 / Shell / subprocess Agent 工具 /
Docker / Redis / PostgreSQL / pgvector / 邮件 / 日历 / 桌面与安卓控制 / 自动 push。
应用为本地单用户开发模式，不得监听公网地址。
