# M3-B 证据（docs/review/M3B_EVIDENCE.md）

阶段：M3-A1 真实模型验收 + M3-B 真实只读工具与证据系统（总管令 006）
分支：phase-3b/real-readonly-tools（自 main ea39c77 创建）
提交：17d9ad1 → 12fedbc（11 个提交：309e850 chore / 0a2193c Evidence+网关 /
5061f1e 只读工具 / 9dc9ba3 工具循环+CLI/API / 3fdf4f1 测试 / be4f4dc 文档 /
fca7436 审查修复 / c775a22 统计口径 / df3c4f0 证据+打包 / 5f3a4e6 AWS 模式 /
12fedbc 数字+marker 修正；git log 见 artifacts/review/m3b-git-log.txt）

## 1. M3-A 遗留 LOW 修复（006 四）

- ModelGateway.budget → frozen BudgetSnapshot 只读视图（四.1）
- OpenAI provider 流式响应读取 + 超限立即断开（四.2）
- 统一秘密检测 app/core/secrets.py：运行时 redact 与打包扫描共用模式集
  （sk-*/ghp_*/AKIA/Bearer/PEM+PKCS#8 整块/通用 key=token=）（四.3/4）
- 打包豁免相对路径精确匹配并打印原因（四.5）；4 项回归测试（四.6）
- DNS rebinding 剩余风险文档（固定 Base URL/禁客户端输入/禁自动重定向/重定向复查）

## 2. Evidence 系统（006 五）

- EvidenceRecord 14 字段 + EvidenceWriter：快照 runtime/evidence/<task_id>/（Git 忽略）、
  哈希去重（重复来源记 metadata.duplicates）、截断 truncated=true、统一脱敏落盘、
  配额（200 条/任务）、去重先于配额。
- 先固化再交模型：Tool Gateway 第 11 步；Claim 只引用 Evidence ID。

## 3. Tool Gateway 升级（006 十一）

- 13 步执行流程：工具查找→角色白名单→只读/风险→参数 Schema→URL/路径安全→
  配额→调用→大小限制→脱敏→Evidence 固化→审计→Evidence 引用。
- ToolPolicy/ToolExecutionContext/ToolQuota（子任务调用数/Evidence 数/读取字节）。
- ToolSpec 扩展 roles/args_schema/url_validator/path_validator/max_result_bytes。
- 模型不得直接接收未处理原始响应；全部拒绝 blocked+审计，handler 不执行。

## 4. 只读工具（006 六/七/八/九/十）

- GitHub：10 工具仅 GET、Token 环境变量私有（repr=False）、401/403/404/429 分类、
  仓库标识校验；无写接口/无 GraphQL mutation。
- web_fetch：SSRF 全套（scheme/凭据/端口/DNS 解析/重定向逐跳复查/解析失败拒绝/
  IPv4-mapped 解映射）；正文提取；UNTRUSTED 标记；不自动访问页面链接。
- Local：7 工具 + LocalPathPolicy（允许根目录服务端配置、project_alias 正则+resolve 复查、
  穿越/符号链接/Junction/UNC/ADS/设备路径/大小写拒绝、敏感文件默认拒绝、大小/条目限制）。
- PDF（pypdf 依赖缺失明确报错/页数/加密/ocr_required）/CSV（无公式执行）/JSON（深度限制）。
- MCP：MCPToolAdapter（静态注册/只读强制/风险重设/黑名单+显式登记双保险）+ FakeMCPServer；
  真实 stdio/http 冒烟标记未配置（10.3）。

## 5. Researcher 工具循环（006 十二）

- 结构化 TOOL_PLAN Schema（不从自由文本解析）；MAX_ROUNDS=3、连续相同调用上限 2、
  子任务调用配额（gateway）、Evidence 数/读取字节配额。
- 无证据 claim 标记未验证；不得自行结束任务；role_used_tool_calls 双口径统计
  （subtask_id 精确 + 旧 role 回退）。

## 6. CLI/API（006 十四/十五）

- CLI：tools/tool-info/allowed-read-roots/evidence/evidence-show/run --project/--allowed-domains。
- API：GET /tools、/tools/{name}、/tasks/{id}/evidence、/evidence/{id}；
  POST /tasks 增 tool_profile/project_alias/allowed_domains（客户端不能传 Key/绝对路径/动态 MCP）。
- evidence_id 严格 hex 校验（防 glob 穿越）；real 未启用 CLI 明确拒绝（预检）。

## 7. 测试结果

- pytest：**183 passed + 1 skipped**（117 M1/M2/M3-A 回归 + 66 M3-B 新增：
  54 项 006 十六 + 8 项审查回归 + 4 项 LOW 修复；symlink 测试 Windows skip 注明）。
- Ruff format --check：64 files already formatted；Ruff check：All checks passed。
- mypy app：43 source files no issues。
- 默认真实网络请求次数：0（MockTransport + IP 字面量，零真实网络/零真实 DNS）。
- 真实网络测试单独标记 manual_integration（未混入 pytest）。

## 8. 真实模型验收与真实端到端

- 环境无 AI_TEAM_MODEL_ENABLE_REAL=true、无 API Key、无 .env →
  **BLOCKED_BY_CREDENTIALS**（M3-A1 三次实测与三条真实任务均未运行，不伪造成功）。
- 证据：`ai-team-os run github_real_compare --model-mode real` → CLI 明确拒绝
  "real model calls disabled"（m3b_real_rejected.txt）。
- M3-B 代码就绪 + 全部离线/Mock 测试全绿。

## 9. 双重审查

- 普通 review（sa_20260805_035741 三轮 continue_from）：最终 verdict=pass。
  修复：角色白名单（Blocking-1）、project_alias 穿越（Blocking-2）、evidence_id glob 穿越、
  IPv4-mapped SSRF、大小写敏感目录、MCP 黑名单说明、root 列示、去重顺序、
  token repr、统计双口径（subtask_id 精确）、alias 显式报错；全部有回归测试。
- Security review（sa_20260805_040412）：最终 verdict=pass，无 CRITICAL/HIGH。
- 遗留 MEDIUM/LOW（不阻塞）：打包脚本 INCLUDE_FILES 分支未统一走过滤（m3b 脚本已修）；
  web_fetch 无 content-type 时按文本解码（建议非文本前缀拒绝）；MCP 未接线运行时
  （真实接入前需集成测试）；DNS rebinding 连接侧 TOCTOU（记录在案）。

## 10. 演示产物（artifacts/demo/）

- m3b_tools.txt：只读工具目录（fixture + github×10 + web_fetch）
- m3b_allowed_roots.txt：未配置根目录（本地工具不可用）
- m3b_fake_run.txt：fake 模式 github_compare_team → completed
- m3b_evidence.txt：evidence_count=2（Evidence 固化生效）
- m3b_real_rejected.txt：real 未启用 → CLI 明确拒绝（BLOCKED_BY_CREDENTIALS 证明）
