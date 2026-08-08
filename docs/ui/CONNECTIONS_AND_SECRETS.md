# Connections & Secrets（010 二十六~三十六 / 009-A）

## 目标

用户不再通过 `.env` / `reasonix.toml` / Windows 环境变量配置运行凭据；
改为网页 **Settings → Connections** 安全配置。环境变量保留为 Advanced/Deployment
兼容方式。

## 支持的连接

| Provider | 密钥 | 说明 |
| -------- | ---- | ---- |
| OpenAI Compatible | API Key | 任意中转/官方 Base URL（不写死 api.openai.com） |
| GitHub | Personal Access Token | 只读工具使用；动态读取 |
| Ollama | 无 | 本地 Provider（`local_provider=true`）默认 `http://127.0.0.1:11434` |

## SecretStore（009-A 五）

```python
class SecretStore(Protocol):
    def set_secret(name, value)   # 保存
    def get_secret(name) -> str | None
    def delete_secret(name)
    def has_secret(name) -> bool
```

- `SessionSecretStore`：进程内存，重启失效，不落盘。
- `WindowsSecretStore`：Windows DPAPI 加密后写 `runtime/secrets/<name>.bin`
  （当前用户范围）；非 Windows 明确报错，不降级明文。
- 业务代码不直接 `os.getenv`，统一走 `SecretResolver`
  （Session → SecureStore → ENV → Missing）。

## API

| 端点 | 说明 |
| ---- | ---- |
| `GET /settings/connections` | 状态（configured/storage/health/base_url/models）；**绝不返回 Secret 值或片段** |
| `PUT /settings/connections/{provider}` | 保存（base_url/api_key/models/storage_mode）；API Key 只在请求内存生命周期，响应不回显 |
| `DELETE /settings/connections/{provider}/credential` | 删除 |
| `POST /settings/connections/{provider}/test` | 安全状态映射：healthy / authentication_failed / model_not_found / rate_limited / timeout / unreachable；不返回 Provider 原始错误 |

## 安全规则（010 二十九）

禁止把真实密钥写入：Git、.env、config.json、SQLite 普通字段、Checkpoint、
Memory、Evidence、Artifact、Audit、Runtime Event、Trace、URL、Cookie、
localStorage、sessionStorage、IndexedDB、浏览器错误报告。
任何 `localStorage.setItem("apiKey", ...)` 视为 security review Blocking。

前端 Secret 输入框：`type=password`、`autocomplete=off`、`spellcheck=false`；
提交成功后立即清空组件状态。

## Base URL 校验

- 仅 http/https；默认拒绝 localhost（SSRF）。
- Ollama 本地 Provider 通过 `local_provider=true` 放行 `127.0.0.1:11434`；
  普通公网 Provider 的 localhost 限制不关闭。
- 不得回传凭据/Authorization/Cookie 到前端。
