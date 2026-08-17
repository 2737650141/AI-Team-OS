# AI Team OS — 测试报告

> 报告日期：2026-08-17（Developer Preview 0.1.0 发布前全量回归）
> 环境：Windows 11 / Python 3.11.9 / 本机（无网络依赖，全部测试离线可重复）

## 1. 结果摘要

| 指标 | 数值 |
| --- | --- |
| 测试文件数 | 53 |
| 总用例数 | 691 |
| ✅ 通过 | 691 |
| ❌ 失败 | 0 |
| ⏭️ 跳过 | 2（平台相关可选用例） |
| ⏱️ 耗时 | 100.4 s |

```bash
.venv/Scripts/pytest tests/ -q          # 全量回归命令
.venv/Scripts/ruff check .              # 静态检查：0 错误
.venv/Scripts/mypy app                  # 类型检查：0 错误（121 源文件）
cd web && npx eslint src                # 前端 lint：0 错误
cd web && npm test                      # 前端单测：55 用例通过（12 文件）
```

## 2. 分模块覆盖

| 模块 | 测试文件 | 用例数 | 覆盖内容 |
| --- | --- | --- | --- |
| 权限与安全 | test_permission_modes, test_security_*, test_sec01_incident, test_audit, test_secret_connections, test_m3_governance, test_m3_low_fixes | 198 | 三档权限矩阵、高风险硬拦截、审批流、Secret Store、脱敏、安全事件回归 |
| 沙箱与工作区 | test_m3c_sandbox, test_m3c_workspace, test_m3c_runtime, test_m3c_git, test_m3c_acceptance | 155 | 隔离执行、补丁引擎、回滚、Git 操作、验收门禁 |
| 模型网关 | test_m3_openai_provider, test_custom_providers, test_cache_multi_provider, test_ux03_1_cache, test_m3_rework_cache | 140 | Provider 适配、SSRF 防护、多 Provider 路由、缓存智能、用量记账 |
| 记忆系统 | test_memory_system, test_checkpoint, test_resume_integration | 50 | SQLite FTS、记忆提案、恢复、上下文治理 |
| 多智能体编排 | test_m2_plan, test_m2_registry, test_m2_workflow, test_multi_provider_team, test_runner, test_smoke | 84 | 计划校验、角色注册、工作流、预算、恢复 |
| 工具网关 | test_tool_gateway, test_m3b_github_web, test_m3b_local_evidence_mcp, test_m3b_pdf, test_m3b_review_fixes | 177 | ToolSpec、只读策略、证据落盘、GitHub 工具、PDF 只读 |
| API 与事件 | test_api, test_m3c_api, test_ui_events | 52 | REST/SSE、审批端点、事件流 |
| 语音与桌面 | test_voice_layer, test_windows_action_layer, test_visual_desktop_intelligence, test_desktop_freeze_hotfix, test_ux03_jarvis | 176 | VAD/唤醒词/转写、UIA、桌面视觉、冻结热修复 |
| 用量观测 | test_usage_attribution, test_m6p2_token_observatory, test_m6p2_release_completion, test_hotfix_m6p2 | 102 | Token/成本归属、上下文观测、发布完成门禁 |
| 个性化 | test_adaptive_personalization, test_conversation_session | 44 | 偏好学习、会话管理 |
| 验收评测 | test_m3c_golden, test_product01_*, test_product02_reliability, test_real_model_roles | 136 | 黄金任务、真实模型门禁、可靠性 |

> 注：模块间有交叉计数（部分测试文件覆盖多个模块），上表为覆盖面的定性归纳。

## 3. 发布前修复记录（2026-08-17）

以下问题在发布回归中发现并已修复，全部纳入本次报告：

| 问题 | 根因 | 修复 |
| --- | --- | --- |
| `test_api_reject_pending` 顺序相关失败 | API `_storage()` 单例绑定首个 data dir 后永久缓存，跨测试数据目录时审批记录解析到错误路径 | 改为按 data dir 键控的注册表（生产行为不变，多目录隔离正确） |
| `test_app_has_no_network_imports` 误报 | `cache_intelligence.py` 仅用 `urllib.parse.urlsplit` 做字符串级 URL 归一化，被过宽的网络导入正则命中 | 白名单 + 注释说明（无网络 I/O） |
| `test_source_tree_contains_no_real_capture_files` | 新增 `docs/screenshots/` 产品 UI 截图触发"源树禁止图片"门禁 | 测试显式豁免该目录（截图经 e2e 断言无敏感内容） |
| ruff E501 × 10 | `test_ux03_1_cache.py` 超长行 | 折行格式化 |
| mypy × 18 | `cache_intelligence.py` 构造参数类型、`usage/store.py` 求和/比值类型不严谨 | 显式类型标注与窄化 |
| 前端单测 `__APP_BUILD_SHA__` 含 `-dirty` | 运行测试时工作区有未提交改动 | 提交后复跑通过（SHA 后缀恢复正常） |

## 4. 验收与历史证据

- 里程碑验收报告：`docs/acceptance/`（M6A / M6P / M6P2 / PRODUCT01 / PRODUCT02）
- 评审证据：`docs/review/`、`docs/reviews/`
- 安全评审：`docs/security/`
- CI：`.github/workflows/ci.yml`（Python 3.11 / 3.12：ruff + mypy + pytest）
