# 只读工具安全（docs/security/READONLY_TOOL_SECURITY.md）

对应总管令 006 六/七/八/十的威胁模型。M3-B 实现。

## 1. GitHub（六）

- 仅 GET（客户端无写方法、无 GraphQL mutation 面）。
- Token 只从环境变量 AI_TEAM_GITHUB_TOKEN，私有字段；不进状态/日志/Evidence。
- 仓库标识校验：owner/repo 或 https://github.com/owner/repo；
  拒绝非 GitHub 域名、路径穿越、任意 API Base URL（固定 https://api.github.com）。
- 401/403/404/429 分类明确；无 Token 允许公开仓库（限流处理）。

## 2. Web Fetch（七）

SSRF 拒绝面（app/core/ssrf.py 统一模块，Provider 与 web_fetch 共用）：
localhost/环回/RFC1918/链路本地/保留/组播/云元数据/域名解析到内网/解析失败/
file/ftp/gopher/非 HTTP(S) scheme/URL 内嵌凭据/异常端口。
重定向：手动循环（最多 3 次），每次目标重新校验，保存最终 URL。
内容安全：正文按数据传入（UNTRUSTED_EXTERNAL_CONTENT 标记），
不把网页提示词当系统指令、不自动访问页面内链接、不提交表单/登录/下载可执行文件。
robots/版权：只保存 URL/标题/获取时间/摘要/短引用，不整站复制。

## 3. Local File（八）

- 允许根目录仅来自服务端配置（AI_TEAM_ALLOWED_READ_ROOTS，默认空）；
  客户端不能传任意绝对根目录（project_alias 只映射到根内子目录）。
- 路径安全五步：规范化 → resolve（符号链接/Junction/短路径）→ 根内复查 →
  敏感规则 → 读取。拒绝：绝对路径/../UNC/ADS/设备路径/大小写绕过。
- 敏感文件默认拒绝（即使位于允许根内）：.env*/.pem/.key/id_rsa/id_ed25519/
  credentials*/secrets*/.aws/.ssh/.git/config/浏览器配置。
- 限制：单文件 2MB、目录 500 项、编码检测、二进制拒绝、PDF 页数 100、
  CSV 行列上限、JSON 深度 20。

## 4. MCP（十）

- Server 必须静态注册；用户任务/LLM 不能动态添加。
- 只读强制：写语义关键词命中或无法确定 → 拒绝；不信任 Server 自报安全等级
  （一律重设 SAFE + read_only=True）。
- 所有调用经 Tool Gateway（参数校验/配额/Evidence/审计）。

## 5. 测试保障

54 项测试（十六）全部 MockTransport/Fixture/临时目录，零真实网络、零真实 DNS；
真实网络测试单独标记 manual_integration。
