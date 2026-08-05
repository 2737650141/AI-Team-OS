"""Artifact 模型（007 六）：ArtifactRecord / ArtifactWriter。

Evidence 表示"依据"，Artifact 表示"交付物或变更结果"。
所有文件写入、补丁和测试结果都必须形成 Artifact（可追溯：approval_id/source_evidence_ids）。
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

ARTIFACT_TYPES = {
    "plan",
    "patch",
    "diff",
    "created_file",
    "modified_file",
    "deleted_file_manifest",
    "test_report",
    "command_report",
    "git_commit",
    "final_report",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactRecord(BaseModel):
    """007 六：交付物/变更结果记录。"""

    artifact_id: str
    task_id: str
    subtask_id: str | None = None
    artifact_type: str
    path: str  # 相对 runtime 目录
    content_hash: str
    size: int = 0
    created_at: str = ""
    created_by: str = "executor"  # planner | executor | reviewer | supervisor
    source_evidence_ids: list[str] = Field(default_factory=list)
    approval_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRecord":
        return cls(**data)


class ArtifactWriter:
    """Artifact 固化器：写入 artifacts/ 目录 + 记录索引（JSONL）。线程安全。"""

    def __init__(self, runtime_dir: Path, task_id: str) -> None:
        self._artifacts_dir = runtime_dir / "artifacts"
        self._task_dir = runtime_dir / "workspaces" / task_id / "artifacts"
        self._task_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._artifacts_dir / f"artifacts-{task_id}.jsonl"
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(
        self,
        *,
        artifact_type: str,
        content: str,
        task_id: str,
        subtask_id: str | None = None,
        created_by: str = "executor",
        source_evidence_ids: list[str] | None = None,
        approval_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        filename: str | None = None,
    ) -> ArtifactRecord:
        """固化一条 Artifact：内容落盘 + 索引记录。"""
        if artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"unknown artifact type: {artifact_type}")
        artifact_id = uuid.uuid4().hex[:16]
        fname = filename or f"{artifact_id}.{artifact_type.replace('_', '-')}.txt"
        target = self._task_dir / fname
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]
        target.write_text(content, encoding="utf-8")
        record = ArtifactRecord(
            artifact_id=artifact_id,
            task_id=task_id,
            subtask_id=subtask_id,
            artifact_type=artifact_type,
            path=str(target),
            content_hash=content_hash,
            size=len(content.encode("utf-8")),
            created_at=_now(),
            created_by=created_by,
            source_evidence_ids=source_evidence_ids or [],
            approval_id=approval_id,
            metadata=metadata or {},
        )
        with self._lock:
            with self._index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def load_all(self, task_id: str) -> list[ArtifactRecord]:
        index = self._artifacts_dir / f"artifacts-{task_id}.jsonl"
        records = []
        if index.exists():
            for line in index.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(ArtifactRecord.from_dict(json.loads(line)))
        return records

    def get(self, artifact_id: str, task_id: str) -> ArtifactRecord | None:
        for r in self.load_all(task_id):
            if r.artifact_id == artifact_id:
                return r
        return None

    def read_content(self, record: ArtifactRecord) -> str:
        return Path(record.path).read_text(encoding="utf-8", errors="replace")
