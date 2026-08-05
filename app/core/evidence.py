"""统一 Evidence 系统（006 五）：EvidenceRecord + EvidenceWriter + 快照目录。

原则（5.1）：
- Evidence ID 全局唯一；原始内容与摘要分离；Claim 只引用 Evidence ID。
- 工具结果必须先固化 Evidence 再交给模型；Reviewer 可经 ID 找到原始快照。
- 内容哈希用于发现变化与去重；同一内容不重复存储。
- 快照目录 runtime/evidence/<task_id>/（Git 忽略）；禁止凭据写入快照（5.2）。
- 内容超限：保存受限快照并标记 truncated=true，不静默假装完整（5.3）。
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.secrets import redact

DEFAULT_MAX_SNAPSHOT_BYTES = 512 * 1024  # 每项快照默认上限（5.3）


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceRecord(BaseModel):
    """统一 Evidence（006 五：字段全集）。"""

    evidence_id: str
    task_id: str
    subtask_id: str | None = None
    tool_name: str
    source_type: str  # github | web | local | mcp | fixture
    source_uri: str
    title: str = ""
    retrieved_at: str
    content_type: str = "text/plain"
    content_hash: str
    content_length: int = 0
    summary: str = ""
    snapshot_ref: str | None = None  # 相对 runtime 目录的快照路径
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    freshness: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    truncated: bool = False
    page_range: list[int] = Field(default_factory=list)  # PDF 页码引用（9.1）
    ocr_required: bool = False  # PDF 无文本（9.1）


class EvidenceQuotaExceeded(Exception):
    """Evidence 配额超限（5.3 / 十二）。"""


class EvidenceWriter:
    """Evidence 固化器：快照落盘 + 哈希去重 + 截断 + 凭据过滤。线程安全。"""

    def __init__(
        self,
        runtime_dir: Path,
        task_id: str,
        max_snapshot_bytes: int = DEFAULT_MAX_SNAPSHOT_BYTES,
        max_evidence_per_task: int = 200,
    ) -> None:
        self._snapshot_dir = runtime_dir / "evidence" / task_id
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._task_id = task_id
        self._max_snapshot_bytes = max_snapshot_bytes
        self._max_evidence = max_evidence_per_task
        self._records: dict[str, EvidenceRecord] = {}
        self._hash_index: dict[str, str] = {}  # content_hash -> evidence_id（去重）
        self._lock = threading.Lock()

    @property
    def snapshot_dir(self) -> Path:
        return self._snapshot_dir

    def write(
        self,
        *,
        tool_name: str,
        source_type: str,
        source_uri: str,
        content: str,
        title: str = "",
        content_type: str = "text/plain",
        subtask_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        reliability: float = 0.5,
        freshness: str | None = None,
        page_range: list[int] | None = None,
        ocr_required: bool = False,
    ) -> EvidenceRecord:
        """固化一条 Evidence（5.1：先固化再交给模型）。"""
        with self._lock:
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]
            # 去重（5.1：同一内容不重复存储）——先去重再查配额（重复内容不消耗配额）
            existing_id = self._hash_index.get(content_hash)
            if existing_id:
                existing = self._records[existing_id]
                existing.metadata.setdefault("duplicates", []).append(
                    {"source_uri": source_uri, "at": _now()}
                )
                return existing
            if len(self._records) >= self._max_evidence:
                raise EvidenceQuotaExceeded(f"evidence quota exceeded: {self._max_evidence}")
            # 截断（5.3）：超限保存受限快照并标记，不静默假装完整
            truncated = False
            raw = content
            if len(raw.encode("utf-8")) > self._max_snapshot_bytes:
                raw = raw.encode("utf-8")[: self._max_snapshot_bytes].decode(
                    "utf-8", errors="replace"
                )
                truncated = True
            # 凭据过滤（5.2）：快照与摘要不得含 API Key/Token/私钥
            safe = redact(raw)
            summary = redact(content[:300])
            evidence_id = uuid.uuid4().hex[:16]
            ext = (
                "txt"
                if content_type == "text/plain"
                else "json"
                if content_type == "application/json"
                else "txt"
            )
            snapshot_ref = f"evidence/{self._task_id}/{evidence_id}.{ext}"
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
            (self._snapshot_dir / f"{evidence_id}.{ext}").write_text(
                safe, encoding="utf-8", errors="replace"
            )
            record = EvidenceRecord(
                evidence_id=evidence_id,
                task_id=self._task_id,
                subtask_id=subtask_id,
                tool_name=tool_name,
                source_type=source_type,
                source_uri=source_uri,
                title=title,
                retrieved_at=_now(),
                content_type=content_type,
                content_hash=content_hash,
                content_length=len(content.encode("utf-8")),
                summary=summary,
                snapshot_ref=snapshot_ref,
                reliability=reliability,
                freshness=freshness,
                metadata=metadata or {},
                truncated=truncated,
                page_range=page_range or [],
                ocr_required=ocr_required,
            )
            self._records[evidence_id] = record
            self._hash_index[content_hash] = evidence_id
            return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self._records.get(evidence_id)

    def records(self) -> list[EvidenceRecord]:
        return list(self._records.values())

    def count(self) -> int:
        return len(self._records)

    def total_bytes(self) -> int:
        return sum(r.content_length for r in self._records.values())

    def snapshot_path(self, evidence_id: str) -> Path | None:
        record = self._records.get(evidence_id)
        if record is None or not record.snapshot_ref:
            return None
        return self._snapshot_dir.parent.parent / record.snapshot_ref
