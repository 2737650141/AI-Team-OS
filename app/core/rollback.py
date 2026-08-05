"""回滚（007 十五）：WorkspaceRollback。

- 回滚单个 Patch（从备份映射恢复目标文件）。
- 回滚到任务初始快照（input/ 只读快照重建 worktree）。
- 恢复删除文件（从回收区）。
- 回滚失败明确报错；回滚操作需 explicit approval；回滚后生成 Artifact。
- Checkpoint 与文件状态保持一致（状态由调用方同步）。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.core.approval import ApprovalError, ApprovalService
from app.core.artifacts import ArtifactWriter
from app.core.patch_engine import _validate_rel_path


class RollbackError(Exception):
    """回滚错误（安全消息）。"""


class WorkspaceRollback:
    """沙箱回滚管理器（十五）。"""

    def __init__(
        self,
        worktree: Path,
        input_dir: Path,
        backups_dir: Path,
        trash_dir: Path,
        artifacts: ArtifactWriter,
        approval: ApprovalService,
        task_id: str,
    ) -> None:
        self._worktree = worktree
        self._input = input_dir
        self._backups = backups_dir
        self._trash = trash_dir
        self._artifacts = artifacts
        self._approval = approval
        self._task_id = task_id

    def _require_approval(self, approval_id: str, action_type: str) -> None:
        request = self._approval.get(approval_id)
        if request is None:
            raise RollbackError("approval not found for rollback")
        if request.action_type != action_type:
            raise RollbackError("approval not bound to rollback action")
        try:
            self._approval.verify_execution(
                request,
                parameter_hash=request.parameter_hash,
                target_hash="",
                operation_hash=request.operation_hash,
            )
        except ApprovalError as exc:
            raise RollbackError(f"approval invalid: {exc}") from exc

    # ---- 回滚单个 Patch ----
    def rollback_patch(self, approval_id: str, patch_approval_id: str) -> dict[str, Any]:
        """回滚指定审批（patch_approval_id）应用的补丁：从备份映射恢复目标文件。"""
        self._require_approval(approval_id, "rollback")
        manifest_path = self._backups / "backup-manifest.jsonl"
        if not manifest_path.exists():
            raise RollbackError("no backup manifest found")
        restored: list[str] = []
        missing: list[str] = []
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("approval_id") != patch_approval_id:
                continue
            target = _validate_rel_path(entry["target"], self._worktree)
            backup = self._backups / entry["backup"]
            if not backup.exists():
                missing.append(entry["target"])
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            restored.append(entry["target"])
        if missing:
            raise RollbackError(f"rollback incomplete; missing backups: {missing}")
        if not restored:
            raise RollbackError(f"no backups found for approval: {patch_approval_id}")
        self._artifacts.write(
            artifact_type="final_report",  # 回滚证据（类型借用 final_report 记录）
            content=json.dumps(
                {
                    "action": "rollback_patch",
                    "patch_approval_id": patch_approval_id,
                    "restored": restored,
                },
                ensure_ascii=False,
                indent=2,
            ),
            task_id=self._task_id,
            created_by="supervisor",
            approval_id=approval_id,
            metadata={"rollback": True, "restored": restored},
        )
        return {"ok": True, "restored": restored}

    # ---- 回滚到初始快照 ----
    def rollback_to_initial(self, approval_id: str) -> dict[str, Any]:
        """回滚到任务初始快照：input/ 重建 worktree（先移旧入回收区）。"""
        self._require_approval(approval_id, "rollback")
        if not self._input.exists():
            raise RollbackError("initial snapshot (input/) missing")
        # 旧 worktree 内容移入回收区（可恢复）
        old_trash = self._trash / f"rollback-{approval_id[:8]}"
        old_trash.mkdir(parents=True, exist_ok=True)
        for item in self._worktree.iterdir():
            shutil.move(str(item), str(old_trash / item.name))
        # 从 input 重建（原子：先复制临时目录再交换）
        tmp = self._worktree.parent / f"worktree-rebuild-{approval_id[:8]}"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(self._input, tmp)
        # 交换
        shutil.rmtree(self._worktree)
        tmp.rename(self._worktree)
        self._artifacts.write(
            artifact_type="final_report",
            content=json.dumps(
                {"action": "rollback_to_initial", "approval_id": approval_id},
                ensure_ascii=False,
                indent=2,
            ),
            task_id=self._task_id,
            created_by="supervisor",
            approval_id=approval_id,
            metadata={"rollback": True, "to_initial": True},
        )
        return {"ok": True, "rolled_back_to_initial": True, "old_in_trash": str(old_trash)}

    # ---- 恢复删除 ----
    def restore_deleted(self, approval_id: str, trash_path: str, target_rel: str) -> dict[str, Any]:
        """从回收区恢复已删除文件（GT 31）。"""
        self._require_approval(approval_id, "rollback")
        trash_item = Path(trash_path)
        if not trash_item.exists():
            raise RollbackError(f"trash item not found: {trash_path}")
        target = _validate_rel_path(target_rel, self._worktree)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(trash_item, target) if trash_item.is_file() else shutil.copytree(
            trash_item, target
        )
        self._artifacts.write(
            artifact_type="final_report",
            content=json.dumps(
                {"action": "restore_deleted", "trash_path": trash_path, "target": target_rel},
                ensure_ascii=False,
                indent=2,
            ),
            task_id=self._task_id,
            created_by="supervisor",
            approval_id=approval_id,
            metadata={"rollback": True, "restore_deleted": True},
        )
        return {"ok": True, "restored": target_rel}
