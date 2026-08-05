# M3-C 证据（总管令 007：M3-B1 封板补齐 + M3-C 沙箱执行、审批与代码修改闭环）

阶段：M3-B1（PDF/验收状态）+ M3-C（沙箱执行/审批/补丁/命令/回滚/Git 闭环）
分支：phase-3c/sandbox-execution（自 main ed89ff3 创建）
提交：ecc94f9(PDF) → dfc1518(acceptance) → f709af4(workspace+approval) →
3fd70c4(sandbox tools+patch+command) → 3d7779a(git) → 539267a(executor 启用) →
e38b29b(runtime+rollback+CLI/API) → 86ea660(reasonix 移除)；git log 见
artifacts/review/m3c-git-log.txt

## 一、M3-B1 封板补齐

- **PDF 真实可用（3.1）**：`pypdf>=4.0,<6.0`（BSD-3-Clause，纯 Python）入项目依赖
  并在 `.venv` 安装（不全局）；`reportlab` 入 dev 依赖（测试合成 PDF 生成）。
  9 项合成 PDF 测试全过：普通文本/多页/页数上限（100）/加密拒绝（不收密码）/
  无文字 `ocr_required=true`/超大（2MB）拒绝/页码引用 page_range/原文件不变/
  依赖版本检查。加密拒绝、不执行 PDF 脚本/附件。
- **验收状态（3.2/3.3）**：五态分类（CODE_READY/MOCK_VALIDATED/REAL_VALIDATED/
  BLOCKED_BY_CREDENTIALS/BLOCKED_BY_CONFIGURATION）；`acceptance-status` 显示
  Provider/模型/GitHub Token 状态（不显示 Token）/允许根/MCP/PDF；`acceptance-run`
  四子项不混入 pytest，无凭据明确报告阻塞不伪造成功。
- **真实模型**：`BLOCKED_BY_CREDENTIALS`（AI_TEAM_MODEL_ENABLE_REAL 未设、
  API Key 空）——见 artifacts/demo/m3c_acceptance_*.txt。
- **真实只读工具**：`BLOCKED_BY_CREDENTIALS`/`CODE_READY`（GitHub Token 未设；
  web 公网可达性未验证；local 需配置允许根）——mock 测试全绿。

## 二、沙箱模型（四）

- WorkspaceManager：六目录 + input 快照 + worktree 写时复制 + 源哈希 +
  WorkspaceManifest；排除 `.env*/密钥/.venv/node_modules/build/.git 敏感文件`；
  大项目配额（50MB/20000 文件）；GT-W10 源项目不变验证。
- 隔离等级：目录沙箱 + 命令白名单，**非容器/虚拟机级强隔离**（文档声明）。

## 三、审批（五）

- ApprovalService/Request/Decision：四等级；操作/参数/目标三哈希绑定 + TTL；
  拒绝不可再批准；重复批准幂等；过期检测；跨进程恢复（JSONL 持久化）；
  LangGraph interrupt 暂停-恢复；GT-W04 参数变化失效；ApprovalPayload
  只含 approval_id/decision/reason。

## 四、写工具 / 补丁 / 命令（七-十）

- 沙箱写工具 7 个（worktree 限定/原子写/备份/删除进回收区/哈希/Artifact）。
- PatchValidator 10 项 + PatchApplier 原子回滚（GT-W08）；预览 Diff（8.3）。
- SandboxCommandRunner：白名单 10+5 命令、禁 shell、注入拒绝（GT-W06）、超时、
  输出限制、脱敏、最小环境、进程树终止、network_isolation=best_effort。

## 五、Executor 与工作流（十二/十三）

- Executor `enabled=true`；只经 Tool Gateway（approval 放行）；工作流：
  提案 → 校验 → Diff Artifact → 审批 interrupt → 恢复验证 → 应用 → 批准测试 →
  Artifact → Reviewer；拒绝路径 rejected_by_user（GT-W03）。

## 六、Reviewer（十四）

- 确定性检查扩展：Executor 未实施/审批缺失/测试失败/无 claims 强制 reject；
  Artifact ID 认可（diff/patch/test_report）；LLM Reviewer 不可覆盖。

## 七、回滚（十五）

- WorkspaceRollback：单 Patch 回滚（备份映射）/初始快照（input 重建）/删除恢复；
  需 explicit approval；回滚 Artifact；失败明确报错。

## 八、Git 闭环（十一）

- 沙箱独立仓库（-b main，无 remote，hooks 指向空目录，本地身份，--local 配置）；
  status/diff/log/add 指定路径/本地 commit（explicit 审批 + Commit Artifact，
  local_only=true）；push/remote/force 不可达；不修改全局配置。

## 九、黄金任务 GT-W01~W10

- 全部通过（tests/test_m3c_golden.py 11 项 + test_m3c_runtime.py 10 项）：
  创建文件/修复 Bug（测试失败→通过）/拒绝审批不应用/篡改检测/路径逃逸预拒绝/
  命令注入拒绝/返工新审批保留历史/多文件原子回滚/本地 commit/源项目保护。

## 十、CLI/API（十六/十七）

- CLI：workspaces/workspace-status/diff/approvals/approval-show/approve/reject/
  artifacts/artifact-show/rollback。
- API：GET /tasks/{run_id}/approvals、/approvals/{id}、/tasks/{run_id}/artifacts、
  /artifacts/{id}、/tasks/{run_id}/diff；POST approve/reject（409 冲突/幂等/
  参数不可改）、/tasks/{run_id}/rollback。

## 十一、测试

- 全量：289 passed + 2 skipped（M1-M3-B 回归 + M3-C 新增 60+ 项）。
- 默认真实网络请求次数：0（全部 MockTransport/IP 字面量）。

## 十二、双重审查

- 普通 review 与 security_review 在最终验证后执行（结论于 §十三 追加）。

## 十三、最终验证与审查结论

（封板时填写）

## 十四、已知限制

- 真实模型/真实只读工具：BLOCKED_BY_CREDENTIALS，未声称真实能力通过。
- 目录沙箱非强隔离；network_isolation=best_effort。
- 真实 MCP Server 未配置（Fake 适配层）；真实 PDF 解析已启用（pypdf）。
- reasonix.toml（运行环境凭据文件）曾误入库，已移除并加入 .gitignore（未 push）。
