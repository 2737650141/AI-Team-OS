"""RuntimeEvent / EventStore（010 十三/十四/二十五）。

- SQLite 持久化（runtime/events.sqlite），sequence 单调递增（AUTOINCREMENT）。
- 按 run_id 查询；SSE 支持 Last-Event-ID replay。
- payload_safe 经 redact() 脱敏；严禁写入 API Key/Token/隐藏推理。
- 单例：init(data_dir) 后 emit() 可在 runner/graph/gateway 复用（本地单进程）。
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.core.secrets import redact

_EVENT_TYPES = {
    "task_created",
    "task_status_changed",
    "task_completed",
    "task_failed",
    "plan_created",
    "subtask_started",
    "subtask_completed",
    "agent_started",
    "agent_completed",
    "agent_failed",
    "model_call_started",
    "model_call_completed",
    "tool_started",
    "tool_completed",
    "tool_blocked",
    "evidence_created",
    "approval_requested",
    "approval_approved",
    "approval_rejected",
    "patch_created",
    "patch_applied",
    "test_started",
    "test_completed",
    "review_started",
    "review_passed",
    "review_rejected",
    "rework_started",
}


class RuntimeEvent(BaseModel):
    """结构化运行时事件（010 十三）。"""

    event_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)  # ISO8601 UTC
    sequence: int = Field(ge=0)
    event_type: str = Field(min_length=1)
    actor_type: str | None = None
    actor_id: str | None = None
    summary: str = Field(default="", max_length=2000)
    payload_safe: dict[str, Any] = Field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EventStore:
    """SQLite 持久化事件存储。"""

    def __init__(self, db_path) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_type TEXT,
                    actor_id TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    payload_safe TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.commit()
            conn.close()

    def emit(
        self,
        *,
        task_id: str | None,
        run_id: str | None,
        event_type: str,
        actor_type: str | None = None,
        actor_id: str | None = None,
        summary: str = "",
        payload_safe: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        if event_type not in _EVENT_TYPES:
            raise ValueError(f"unknown event type: {event_type}")
        # 防御：TaskState.run_id 可为空（早期测试构造）；事件记录用 task_id 兜底
        task_id = task_id or "unknown"
        run_id = run_id or task_id
        if not task_id:
            task_id = "unknown"
        event = RuntimeEvent(
            event_id=uuid.uuid4().hex[:16],
            task_id=task_id,
            run_id=run_id,
            timestamp=_now(),
            sequence=0,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            summary=redact(summary)[:2000],
            payload_safe={},
        )
        # payload 深脱敏（逐字段；绝不写入凭据/隐藏推理）
        event.payload_safe = _safe_payload(payload_safe)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            cur = conn.execute(
                """
                INSERT INTO events
                (event_id, task_id, run_id, timestamp, event_type,
                 actor_type, actor_id, summary, payload_safe)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    event.run_id,
                    event.timestamp,
                    event.event_type,
                    event.actor_type,
                    event.actor_id,
                    event.summary,
                    _json_dumps(event.payload_safe),
                ),
            )
            event.sequence = int(cur.lastrowid or 0)
            conn.commit()
            conn.close()
        return event

    def list_events(
        self, run_id: str | None = None, after_sequence: int = 0, limit: int = 2000
    ) -> list[RuntimeEvent]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                    (run_id, after_sequence, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT ?",
                    (after_sequence, limit),
                ).fetchall()
            conn.close()
        return [_row_to_event(r) for r in rows]

    def latest_sequence(self) -> int:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM events").fetchone()
            conn.close()
        return int(row[0] if row else 0)

    def count(self) -> int:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
            conn.close()
        return int(row[0] if row else 0)


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """payload 逐字段脱敏（嵌套值字符串化后 redact）。"""
    if not payload:
        return {}
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, str):
            out[k] = redact(v)[:2000]
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, dict):
            out[k] = _safe_payload(v)
        elif isinstance(v, list):
            out[k] = [redact(str(x))[:2000] for x in v]
        else:
            out[k] = redact(str(v))[:2000]
    return out


def _json_dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, default=str)


def _row_to_event(row: tuple) -> RuntimeEvent:
    import json

    payload: dict[str, Any] = {}
    try:
        payload = json.loads(row[9] or "{}")
    except (ValueError, TypeError):
        payload = {}
    return RuntimeEvent(
        event_id=row[1],
        task_id=row[2],
        run_id=row[3],
        timestamp=row[4],
        sequence=row[0],
        event_type=row[5],
        actor_type=row[6],
        actor_id=row[7],
        summary=row[8] or "",
        payload_safe=payload,
    )


# ---- 进程级单例（本地单用户） ----
_store: EventStore | None = None
_store_lock = threading.Lock()


def init(data_dir) -> EventStore:
    """初始化全局事件存储（runtime/events.sqlite）。幂等。"""
    global _store
    path = data_dir / "runtime" / "events.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _store_lock:
        if _store is None:
            _store = EventStore(path)
        return _store


def get_store() -> EventStore | None:
    return _store


def emit(
    *,
    task_id: str | None,
    run_id: str | None,
    event_type: str,
    actor_type: str | None = None,
    actor_id: str | None = None,
    summary: str = "",
    payload_safe: dict[str, Any] | None = None,
) -> RuntimeEvent | None:
    if _store is None:
        return None
    return _store.emit(
        task_id=task_id,
        run_id=run_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        summary=summary,
        payload_safe=payload_safe,
    )
