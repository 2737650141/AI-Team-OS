# Secret Store（010 二十六~二十八 / 009-A 五）

## 接口

```python
class SecretStore(Protocol):
    def set_secret(name, value) -> None
    def get_secret(name) -> str | None
    def delete_secret(name) -> None
    def has_secret(name) -> bool
```

## 实现

| 实现 | 存储 | 生命周期 | 平台 |
| ---- | ---- | -------- | ---- |
| `SessionSecretStore` | 进程内存 | 后端重启失效 | 任意 |
| `WindowsSecretStore` | DPAPI 加密文件 `runtime/secrets/<name>.bin` | 持久（当前用户范围） | Windows（非 Windows 明确报错） |

未来可扩展：MacOS Keychain / Linux Secret Service（封装在 SecretStore 抽象后，
业务层不直接依赖平台实现）。

## SecretResolver（010 二十八）

```text
Session → Windows Secure Store → Environment Variable → Missing
```

- 业务代码禁止散落 `os.getenv(...)` 读取真实凭据。
- 环境变量保留为向后兼容（Advanced/Deployment 模式）。
- `store_mode()` 返回存储来源标签（session / windows_secure_store /
  environment_variable / missing），绝不返回值。

## 禁止持久化位置（010 二十九）

Git / .env / reasonix.toml / config.json / SQLite 普通字段 / Checkpoint / Memory /
Evidence / Artifact / Audit / Runtime Event / Trace / URL / Cookie /
localStorage / sessionStorage / IndexedDB / React Query persistence /
Zustand persistence / Console / Analytics / Error Report。

## 安全要求

- DPAPI 加密使用当前用户范围（无需管理员权限）。
- 保存时 API Key 仅存在于本次 HTTP 请求内存生命周期；存储完成后立即释放引用。
- UI 只显示 `Configured / Connected / Last checked`，不返回、不显示、不回填
  完整密钥（连后四位也不显示）。
- Replace 流程：输入新 Key → Test → 保存（旧 Key 从本机 SecretStore 删除）；
  UI 提示"这不会在 Provider 后台吊销旧密钥"。
