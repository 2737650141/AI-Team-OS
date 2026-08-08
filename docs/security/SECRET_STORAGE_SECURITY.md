# Secret 存储安全（010 四十九 / 009-A 二十二）

## 威胁模型

本地单用户环境（127.0.0.1），威胁主要是：密钥误持久化到可被误提交/误打包的位置、
前端脚本读取密钥、日志/事件/证据回显密钥、跨用户读取 DPAPI 数据。

## 控制

1. **存储层**：SessionSecretStore（内存）与 WindowsSecretStore（DPAPI 当前用户）。
   - DPAPI 密文依赖当前 Windows 用户上下文，其他用户/机器无法解密。
   - 文件仅含密文；名称白名单 `[A-Za-z0-9._-]`。
2. **读取层**：SecretResolver 统一入口，优先级 Session → Secure → ENV；环境变量
   仅作向后兼容。
3. **传输层**：仅 127.0.0.1 HTTP；API Key 只在请求内存生命周期。
4. **前端**：无任何浏览器持久化；表单提交后清空。
5. **审计**：Audit/Event/Evidence/Artifact/Trace 全部脱敏（`redact()`）。
6. **打包**：`make_m3c_zip.py` / UI 证据包使用共享 `SECRET_PATTERNS` 扫描；
   pre-commit hook 阻塞含真实密钥的提交。

## 安全测试（tests/test_secret_connections.py）

- Session 不落盘、重启失效 ✓
- Resolver 优先级（Session > Secure > ENV）✓
- 环境变量回退 ✓
- Windows round-trip（DPAPI 加密解密）✓
- `GET /settings/connections` 无 Secret ✓
- PUT 保存不回显；DELETE 后 configured=false ✓
- Test Connection 无凭据 → authentication_failed（不发网络）✓
- Base URL SSRF（localhost 拒绝 / 非 http 拒绝）✓
- Ollama 本地 Provider 放行 ✓

## 已知边界

- WindowsSecretStore 在非 Windows 平台不可用（明确报错，不降级明文）——Linux/macOS
  需实现 Secret Service/Keychain 后启用。
- 浏览器端安全依赖 CSP/同源：本项目仅本机回环，无第三方脚本。
