"""SQLite + FTS5 persistence for Controlled Memory.

All writes are transactional. Secrets never belong in this store; callers must
pass policy before persistence, and the store defensively rejects secret rows.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, List

from app.memory.models import (
    MemoryHealth,
    MemoryProposal,
    MemoryRecord,
    MemorySettings,
    MemoryUsage,
    PreferenceSignal,
    utc_now,
)

SCHEMA_VERSION = 1
_ACTIVE_STATUSES = ("active", "confirmed")


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _migrate(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    memory_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    value TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    privacy_level TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    expires_at TEXT,
                    supersedes TEXT,
                    superseded_by TEXT,
                    confirmation_required INTEGER NOT NULL,
                    confirmed_by_user INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    retention TEXT NOT NULL DEFAULT 'manual',
                    FOREIGN KEY(supersedes) REFERENCES memories(memory_id),
                    FOREIGN KEY(superseded_by) REFERENCES memories(memory_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_scope
                    ON memories(user_id, project_id, status, memory_type);
                CREATE INDEX IF NOT EXISTS idx_memory_expiry ON memories(status, expires_at);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_memory_fact
                    ON memories(user_id, COALESCE(project_id, ''), memory_type, subject, predicate)
                    WHERE status IN ('active', 'confirmed');

                CREATE TABLE IF NOT EXISTS memory_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    memory_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    proposed_value TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    privacy_level TEXT NOT NULL,
                    confirmation_required INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    retention TEXT NOT NULL DEFAULT 'manual',
                    expires_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_proposal_status
                    ON memory_proposals(user_id, project_id, status);

                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id TEXT PRIMARY KEY,
                    memory_id TEXT,
                    proposal_id TEXT,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_links (
                    link_id TEXT PRIMARY KEY,
                    from_memory_id TEXT NOT NULL,
                    to_memory_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(from_memory_id, to_memory_id, relation)
                );
                CREATE TABLE IF NOT EXISTS memory_confirmations (
                    confirmation_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    edited INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_usage (
                    usage_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    memory_id TEXT NOT NULL,
                    memory_version INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    reason_selected TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    used_at TEXT NOT NULL,
                    UNIQUE(run_id, memory_id, memory_version, role)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_usage_run ON memory_usage(run_id, used_at);
                CREATE TABLE IF NOT EXISTS preference_signals (
                    signal_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    signal_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, signal_type, value, task_id)
                );
                CREATE TABLE IF NOT EXISTS memory_settings (
                    user_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    automatic_low_risk INTEGER NOT NULL,
                    preference_detection INTEGER NOT NULL,
                    retention TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    memory_id UNINDEXED,
                    subject,
                    predicate,
                    normalized_value,
                    tags,
                    project_id
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()

    def create_proposal(self, proposal: MemoryProposal) -> MemoryProposal:
        if proposal.privacy_level == "secret":
            raise ValueError("secret content cannot be persisted as a proposal")
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO memory_proposals VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal.proposal_id,
                    proposal.user_id,
                    proposal.project_id,
                    proposal.memory_type,
                    proposal.subject,
                    proposal.predicate,
                    proposal.proposed_value,
                    proposal.reason,
                    proposal.source_type,
                    proposal.source_ref,
                    proposal.confidence,
                    proposal.privacy_level,
                    int(proposal.confirmation_required),
                    proposal.created_at,
                    proposal.status,
                    json.dumps(proposal.tags, ensure_ascii=False),
                    proposal.retention,
                    proposal.expires_at,
                ),
            )
            self._event(conn, "memory_proposed", proposal_id=proposal.proposal_id)
            conn.commit()
        return proposal

    def get_proposal(self, proposal_id: str) -> MemoryProposal | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        return self._proposal(row) if row else None

    def list_proposals(
        self,
        *,
        user_id: str = "local-user",
        project_id: str | None = None,
        status: str = "proposed",
    ) -> list[MemoryProposal]:
        sql = "SELECT * FROM memory_proposals WHERE user_id=? AND status=?"
        params: list[Any] = [user_id, status]
        if project_id is not None:
            sql += " AND project_id=?"
            params.append(project_id)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._proposal(row) for row in rows]

    def reject_proposal(self, proposal_id: str) -> MemoryProposal:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            if row["status"] != "proposed":
                raise ValueError("proposal is no longer pending")
            conn.execute(
                "UPDATE memory_proposals SET status='rejected' WHERE proposal_id=?",
                (proposal_id,),
            )
            self._confirmation(conn, proposal_id, "reject", edited=False)
            self._event(conn, "memory_rejected", proposal_id=proposal_id)
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM memory_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        return self._proposal(updated)

    def confirm_proposal(self, proposal_id: str, edited_value: str | None = None) -> MemoryRecord:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            if row["status"] != "proposed":
                raise ValueError("proposal is no longer pending")
            value = edited_value.strip() if edited_value is not None else row["proposed_value"]
            if not value:
                raise ValueError("memory value cannot be empty")
            now = utc_now()
            memory_id = f"mem_{uuid.uuid4().hex[:16]}"
            supersedes = self._supersede_conflict(
                conn,
                user_id=row["user_id"],
                project_id=row["project_id"],
                memory_type=row["memory_type"],
                subject=row["subject"],
                predicate=row["predicate"],
                new_memory_id=memory_id,
            )
            normalized = self.normalize(value)
            content_hash = self.content_hash(
                row["subject"], row["predicate"], normalized, row["project_id"]
            )
            record = MemoryRecord(
                memory_id=memory_id,
                user_id=row["user_id"],
                project_id=row["project_id"],
                memory_type=row["memory_type"],
                subject=row["subject"],
                predicate=row["predicate"],
                value=value,
                normalized_value=normalized,
                confidence=row["confidence"],
                status="active",
                privacy_level=row["privacy_level"],
                source_type="user_confirmation",
                source_ref=row["source_ref"],
                created_at=now,
                updated_at=now,
                expires_at=row["expires_at"],
                supersedes=supersedes,
                confirmation_required=bool(row["confirmation_required"]),
                confirmed_by_user=True,
                version=1,
                content_hash=content_hash,
                tags=json.loads(row["tags_json"] or "[]"),
                retention=row["retention"],
            )
            self._deactivate_superseded(conn, supersedes)
            self._insert_memory(conn, record)
            self._mark_superseded(conn, supersedes, memory_id)
            conn.execute(
                "UPDATE memory_proposals SET status='confirmed' WHERE proposal_id=?",
                (proposal_id,),
            )
            self._sync_fts(conn, memory_id)
            self._confirmation(
                conn, proposal_id, "edit_confirm" if edited_value else "confirm", bool(edited_value)
            )
            self._event(conn, "memory_confirmed", memory_id=memory_id, proposal_id=proposal_id)
            conn.commit()
            result = conn.execute(
                "SELECT * FROM memories WHERE memory_id=?", (memory_id,)
            ).fetchone()
        return self._memory(result)

    def add_active(self, record: MemoryRecord) -> MemoryRecord:
        if record.privacy_level == "secret":
            raise ValueError("secret content cannot enter memory store")
        with self._lock, self._connect() as conn:
            supersedes = self._supersede_conflict(
                conn,
                user_id=record.user_id,
                project_id=record.project_id,
                memory_type=record.memory_type,
                subject=record.subject,
                predicate=record.predicate,
                new_memory_id=record.memory_id,
            )
            payload = record.model_copy(update={"supersedes": supersedes, "status": "active"})
            self._deactivate_superseded(conn, supersedes)
            self._insert_memory(conn, payload)
            self._mark_superseded(conn, supersedes, payload.memory_id)
            self._sync_fts(conn, payload.memory_id)
            self._event(conn, "memory_confirmed", memory_id=payload.memory_id)
            conn.commit()
        return payload

    def get(self, memory_id: str) -> MemoryRecord | None:
        self.expire_due()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        return self._memory(row) if row else None

    def list(
        self,
        *,
        user_id: str = "local-user",
        project_id: str | None = None,
        status: str | None = None,
        memory_type: str | None = None,
        source_type: str | None = None,
        include_global: bool = False,
        limit: int = 500,
    ) -> List[MemoryRecord]:
        self.expire_due()
        sql = "SELECT * FROM memories WHERE user_id=?"
        params: list[Any] = [user_id]
        if project_id is not None:
            if include_global:
                sql += " AND (project_id=? OR project_id IS NULL)"
            else:
                sql += " AND project_id=?"
            params.append(project_id)
        if status:
            sql += " AND status=?"
            params.append(status)
        if memory_type:
            sql += " AND memory_type=?"
            params.append(memory_type)
        if source_type:
            sql += " AND source_type=?"
            params.append(source_type)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 10_000)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._memory(row) for row in rows]

    def search(
        self,
        query: str,
        *,
        user_id: str = "local-user",
        project_id: str | None = None,
        status: str | None = None,
        memory_type: str | None = None,
        source_type: str | None = None,
        limit: int = 100,
    ) -> List[MemoryRecord]:
        self.expire_due()
        terms = re.findall(r"[\w\u3400-\u9fff-]+", query, flags=re.UNICODE)
        if not terms:
            return self.list(
                user_id=user_id,
                project_id=project_id,
                status=status,
                memory_type=memory_type,
                source_type=source_type,
                include_global=project_id is not None,
                limit=limit,
            )
        match = " AND ".join(f'"{term.replace(chr(34), "")}"' for term in terms[:12])
        sql = (
            "SELECT m.* FROM memories_fts f JOIN memories m ON m.memory_id=f.memory_id "
            "WHERE memories_fts MATCH ? AND m.user_id=?"
        )
        params: list[Any] = [match, user_id]
        if project_id is not None:
            sql += " AND (m.project_id=? OR m.project_id IS NULL)"
            params.append(project_id)
        if status:
            sql += " AND m.status=?"
            params.append(status)
        if memory_type:
            sql += " AND m.memory_type=?"
            params.append(memory_type)
        if source_type:
            sql += " AND m.source_type=?"
            params.append(source_type)
        sql += " ORDER BY bm25(memories_fts), m.confidence DESC, m.updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._memory(row) for row in rows]

    def forget(self, memory_id: str, actor: str = "user") -> MemoryRecord:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
            if row is None:
                raise KeyError(memory_id)
            now = utc_now()
            # Wipe content, not only status. Audit keeps identifiers and action, never text.
            conn.execute(
                """UPDATE memories SET status='forgotten', value='', normalized_value='',
                tags_json='[]', content_hash=?, updated_at=?, version=version+1
                WHERE memory_id=?""",
                (self.content_hash(memory_id, "forgotten", "", None), now, memory_id),
            )
            conn.execute("DELETE FROM memories_fts WHERE memory_id=?", (memory_id,))
            self._event(conn, "memory_forgotten", memory_id=memory_id, actor=actor)
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM memories WHERE memory_id=?", (memory_id,)
            ).fetchone()
        return self._memory(updated)

    def forget_project(self, project_id: str, user_id: str = "local-user") -> int:
        records = self.list(user_id=user_id, project_id=project_id, limit=10_000)
        count = 0
        for record in records:
            if record.status not in {"forgotten", "expired"}:
                self.forget(record.memory_id)
                count += 1
        return count

    def expire_due(self, now: str | None = None) -> int:
        now = now or utc_now()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT memory_id FROM memories
                WHERE status IN ('active','confirmed') AND expires_at IS NOT NULL
                AND expires_at<=?""",
                (now,),
            ).fetchall()
            for row in rows:
                memory_id = row["memory_id"]
                conn.execute(
                    """UPDATE memories SET status='expired', updated_at=?, version=version+1
                    WHERE memory_id=?""",
                    (now, memory_id),
                )
                conn.execute("DELETE FROM memories_fts WHERE memory_id=?", (memory_id,))
                self._event(conn, "memory_expired", memory_id=memory_id)
            conn.commit()
        return len(rows)

    def record_usage(self, usage: MemoryUsage) -> bool:
        with self._lock, self._connect() as conn:
            inserted = conn.execute(
                """INSERT OR IGNORE INTO memory_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    usage.usage_id,
                    usage.run_id,
                    usage.memory_id,
                    usage.memory_version,
                    usage.role,
                    usage.reason_selected,
                    usage.scope,
                    usage.token_count,
                    usage.used_at,
                ),
            )
            conn.execute(
                "UPDATE memories SET last_used_at=?, updated_at=updated_at WHERE memory_id=?",
                (usage.used_at, usage.memory_id),
            )
            if inserted.rowcount:
                self._event(
                    conn,
                    "memory_used",
                    memory_id=usage.memory_id,
                    details={
                        "run_id": usage.run_id,
                        "role": usage.role,
                        "version": usage.memory_version,
                    },
                )
            conn.commit()
        return bool(inserted.rowcount)

    def usage_for_run(self, run_id: str) -> List[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT u.*, m.subject, m.predicate, m.value, m.project_id, m.source_type,
                m.source_ref, m.status FROM memory_usage u
                JOIN memories m ON m.memory_id=u.memory_id
                WHERE u.run_id=? ORDER BY u.used_at, u.role""",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_signal(self, signal: PreferenceSignal) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO preference_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    signal.signal_id,
                    signal.user_id,
                    signal.project_id,
                    signal.signal_type,
                    signal.value,
                    signal.task_id,
                    signal.source_ref,
                    signal.created_at,
                ),
            )
            conn.commit()
        return bool(cur.rowcount)

    def signals(self, *, user_id: str, signal_type: str, value: str) -> List[PreferenceSignal]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM preference_signals
                WHERE user_id=? AND signal_type=? AND value=? ORDER BY created_at""",
                (user_id, signal_type, value),
            ).fetchall()
        return [PreferenceSignal(**dict(row)) for row in rows]

    def get_settings(self, user_id: str = "local-user") -> MemorySettings:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_settings WHERE user_id=?", (user_id,)
            ).fetchone()
        if row is None:
            return MemorySettings()
        return MemorySettings(
            enabled=bool(row["enabled"]),
            automatic_low_risk=bool(row["automatic_low_risk"]),
            preference_detection=bool(row["preference_detection"]),
            retention=row["retention"],
        )

    def set_settings(self, settings: MemorySettings, user_id: str = "local-user") -> MemorySettings:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO memory_settings VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,
                automatic_low_risk=excluded.automatic_low_risk,
                preference_detection=excluded.preference_detection,
                retention=excluded.retention, updated_at=excluded.updated_at""",
                (
                    user_id,
                    int(settings.enabled),
                    int(settings.automatic_low_risk),
                    int(settings.preference_detection),
                    settings.retention,
                    utc_now(),
                ),
            )
            conn.commit()
        return settings

    def health(self) -> MemoryHealth:
        with self._connect() as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            memories = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            pending = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_proposals WHERE status='proposed'"
                ).fetchone()[0]
            )
            version = int(
                conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[
                    0
                ]
            )
        return MemoryHealth(
            schema_version=version,
            integrity=integrity,
            fts5=True,
            memories=memories,
            pending=pending,
        )

    def backup(self, target: Path | None = None) -> Path:
        target = target or self.db_path.parent / "backups" / f"memory-{utc_now()[:10]}.sqlite"
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as source, sqlite3.connect(str(target)) as dest:
            source.backup(dest)
        return target

    def restore(self, source: Path) -> None:
        if not source.is_file():
            raise FileNotFoundError(source)
        with sqlite3.connect(str(source)) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("memory backup integrity check failed")
        with (
            self._lock,
            sqlite3.connect(str(source)) as source_conn,
            sqlite3.connect(str(self.db_path)) as destination,
        ):
            source_conn.backup(destination)
        self._migrate()

    def export(self, user_id: str = "local-user") -> dict[str, Any]:
        records = self.list(user_id=user_id, limit=10_000)
        safe = [
            record.model_dump(
                exclude={"content_hash"},
                mode="json",
            )
            for record in records
            if record.privacy_level != "secret" and record.status != "forgotten"
        ]
        return {"schema_version": SCHEMA_VERSION, "exported_at": utc_now(), "memories": safe}

    def _supersede_conflict(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        project_id: str | None,
        memory_type: str,
        subject: str,
        predicate: str,
        new_memory_id: str,
    ) -> str | None:
        row = conn.execute(
            """SELECT memory_id FROM memories WHERE user_id=? AND project_id IS ?
            AND memory_type=? AND subject=? AND predicate=? AND status IN ('active','confirmed')""",
            (user_id, project_id, memory_type, subject, predicate),
        ).fetchone()
        if row is None:
            return None
        old_id = str(row["memory_id"])
        return old_id

    def _mark_superseded(
        self, conn: sqlite3.Connection, old_memory_id: str | None, new_memory_id: str
    ) -> None:
        if old_memory_id is None:
            return
        conn.execute(
            """UPDATE memories SET superseded_by=?, updated_at=? WHERE memory_id=?""",
            (new_memory_id, utc_now(), old_memory_id),
        )
        conn.execute("DELETE FROM memories_fts WHERE memory_id=?", (old_memory_id,))
        self._event(
            conn,
            "memory_superseded",
            memory_id=old_memory_id,
            details={"superseded_by": new_memory_id},
        )

    @staticmethod
    def _deactivate_superseded(conn: sqlite3.Connection, old_memory_id: str | None) -> None:
        if old_memory_id is None:
            return
        conn.execute(
            """UPDATE memories SET status='superseded', updated_at=?, version=version+1
            WHERE memory_id=?""",
            (utc_now(), old_memory_id),
        )
        conn.execute("DELETE FROM memories_fts WHERE memory_id=?", (old_memory_id,))

    def _sync_fts(self, conn: sqlite3.Connection, memory_id: str) -> None:
        conn.execute("DELETE FROM memories_fts WHERE memory_id=?", (memory_id,))
        row = conn.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        if row is None or row["status"] not in _ACTIVE_STATUSES:
            return
        conn.execute(
            "INSERT INTO memories_fts VALUES (?, ?, ?, ?, ?, ?)",
            (
                memory_id,
                row["subject"],
                row["predicate"],
                row["normalized_value"],
                " ".join(json.loads(row["tags_json"] or "[]")),
                row["project_id"] or "global",
            ),
        )

    def _confirmation(
        self, conn: sqlite3.Connection, proposal_id: str, action: str, edited: bool
    ) -> None:
        conn.execute(
            "INSERT INTO memory_confirmations VALUES (?, ?, ?, ?, ?)",
            (f"mc_{uuid.uuid4().hex[:16]}", proposal_id, action, int(edited), utc_now()),
        )

    def _event(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        *,
        memory_id: str | None = None,
        proposal_id: str | None = None,
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO memory_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"me_{uuid.uuid4().hex[:16]}",
                memory_id,
                proposal_id,
                event_type,
                actor,
                json.dumps(details or {}, ensure_ascii=False),
                utc_now(),
            ),
        )

    @staticmethod
    def normalize(value: str) -> str:
        return " ".join(value.strip().lower().split())

    @staticmethod
    def content_hash(subject: str, predicate: str, normalized: str, project_id: str | None) -> str:
        raw = "\x1f".join([subject, predicate, normalized, project_id or "global"])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _memory_values(record: MemoryRecord) -> tuple[Any, ...]:
        return (
            record.memory_id,
            record.user_id,
            record.project_id,
            record.memory_type,
            record.subject,
            record.predicate,
            record.value,
            record.normalized_value,
            record.confidence,
            record.status,
            record.privacy_level,
            record.source_type,
            record.source_ref,
            record.created_at,
            record.updated_at,
            record.last_used_at,
            record.expires_at,
            record.supersedes,
            record.superseded_by,
            int(record.confirmation_required),
            int(record.confirmed_by_user),
            record.version,
            record.content_hash,
            json.dumps(record.tags, ensure_ascii=False),
            record.retention,
        )

    def _insert_memory(self, conn: sqlite3.Connection, record: MemoryRecord) -> None:
        placeholders = ", ".join("?" for _ in self._memory_values(record))
        conn.execute(
            f"INSERT INTO memories VALUES ({placeholders})",  # noqa: S608 - fixed placeholders
            self._memory_values(record),
        )

    @staticmethod
    def _memory(row: sqlite3.Row) -> MemoryRecord:
        data = dict(row)
        data["tags"] = json.loads(data.pop("tags_json") or "[]")
        data["confirmation_required"] = bool(data["confirmation_required"])
        data["confirmed_by_user"] = bool(data["confirmed_by_user"])
        return MemoryRecord(**data)

    @staticmethod
    def _proposal(row: sqlite3.Row) -> MemoryProposal:
        data = dict(row)
        data["tags"] = json.loads(data.pop("tags_json") or "[]")
        data["confirmation_required"] = bool(data["confirmation_required"])
        return MemoryProposal(**data)
