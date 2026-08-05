# 补丁引擎（007 八）

## 组件

- `PatchProposal`：patch_id / task_id / subtask_id / base_revision / target_files /
  unified_diff / reason / expected_effect / risk_summary / tests_to_run /
  source_evidence_ids。
- `PatchValidator`：应用前 10 项确定性校验（8.2）。
- `PatchApplier`：受控 Python 补丁应用（不通过 Shell 调用 `patch`）。

## 10 项校验（8.2）

1. Unified Diff 格式有效（含 hunk）。
2. 所有目标位于 worktree（绝对/穿越/UNC/ADS 拒绝）。
3. Base 文件哈希匹配。
4. 禁止修改被禁止路径（`.env*`/`.ssh`/`.git`/私钥等）。
5. 禁止写敏感文件（`.pem/.key/.p12/.p8/.pfx/.ppk`）。
6. 不允许创建超大文件（单文件 2MB 上限）。
7. 不允许修改二进制文件（NUL 字节检测）。
8. 路径重命名逃逸（resolve 复查）。
9. 变更文件数 ≤ 50。
10. 变更总行数 ≤ 5000。

## 预览（8.3）

审批前生成 Diff Artifact、变更摘要、风险摘要、预计测试。**用户必须先看到 Diff，
才能批准应用。**

## 应用（8.4）

- 受控 Python 实现（`difflib`-风格 hunk 应用），非 `patch` 命令。
- 应用前备份（`backups/` + `backup-manifest.jsonl` 记录 approval_id→target→backup）。
- 任一文件失败 → 整个 Patch 原子回滚（恢复全部备份）。
- 成功后生成修改后哈希；不允许部分成功却标记完成。

## 回滚（007 十五）

`WorkspaceRollback`：单 Patch 回滚（按备份映射恢复）、回滚到初始快照（input/
重建 worktree）、恢复删除（回收区）。回滚需 explicit approval（action_type=rollback），
回滚后生成 Artifact，Checkpoint 与文件状态保持一致。
