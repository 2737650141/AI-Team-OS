"""Persistence for controls and proposal cooldowns, never a preference truth store."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.memory.models import utc_now


class PersonalizationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS personalization_controls (
                    user_id TEXT NOT NULL,
                    project_key TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    field TEXT NOT NULL,
                    override_value TEXT,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, project_key, task_type, field)
                );
                CREATE TABLE IF NOT EXISTS personalization_suppressions (
                    user_id TEXT NOT NULL,
                    project_key TEXT NOT NULL,
                    field TEXT NOT NULL,
                    rejected_at_task INTEGER NOT NULL,
                    suppress_until_task INTEGER NOT NULL,
                    suppress_forever INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, project_key, field)
                );
                CREATE TABLE IF NOT EXISTS personalization_task_counters (
                    user_id TEXT NOT NULL,
                    project_key TEXT NOT NULL,
                    task_count INTEGER NOT NULL,
                    PRIMARY KEY(user_id, project_key)
                );
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _project(project_id: str | None) -> str:
        return project_id or ""

    def begin_task(self, user_id: str, project_id: str | None) -> int:
        project = self._project(project_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO personalization_task_counters VALUES (?, ?, 1)
                ON CONFLICT(user_id, project_key) DO UPDATE SET task_count=task_count+1""",
                (user_id, project),
            )
            row = conn.execute(
                "SELECT task_count FROM personalization_task_counters "
                "WHERE user_id=? AND project_key=?",
                (user_id, project),
            ).fetchone()
            conn.commit()
        return int(row["task_count"] if row else 1)

    def task_count(self, user_id: str, project_id: str | None) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT task_count FROM personalization_task_counters "
                "WHERE user_id=? AND project_key=?",
                (user_id, self._project(project_id)),
            ).fetchone()
        return int(row["task_count"] if row else 0)

    def controls(
        self, user_id: str, project_id: str | None, task_type: str
    ) -> list[dict[str, Any]]:
        keys = ("", self._project(project_id)) if project_id else ("",)
        placeholders = ",".join("?" for _ in keys)
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM personalization_controls WHERE user_id=?
                AND project_key IN ({placeholders}) AND task_type IN ('', ?)
                ORDER BY (project_key<>'') ASC, (task_type<>'') ASC""",
                (user_id, *keys, task_type),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_control(
        self,
        *,
        field: str,
        value: str | None,
        enabled: bool,
        user_id: str = "local-user",
        project_id: str | None = None,
        task_type: str = "",
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO personalization_controls VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, project_key, task_type, field) DO UPDATE SET
                override_value=excluded.override_value, enabled=excluded.enabled,
                updated_at=excluded.updated_at""",
                (
                    user_id,
                    self._project(project_id),
                    task_type,
                    field,
                    value,
                    int(enabled),
                    utc_now(),
                ),
            )
            conn.commit()

    def reset(self, user_id: str, project_id: str | None = None, field: str | None = None) -> int:
        query = "DELETE FROM personalization_controls WHERE user_id=?"
        params: list[Any] = [user_id]
        if project_id is not None:
            query += " AND project_key=?"
            params.append(self._project(project_id))
        if field is not None:
            query += " AND field=?"
            params.append(field)
        with self._lock, self._connect() as conn:
            cur = conn.execute(query, params)
            conn.commit()
        return int(cur.rowcount)

    def reject_proposal(
        self,
        field: str,
        project_id: str | None,
        *,
        user_id: str = "local-user",
        cooldown_tasks: int = 3,
        forever: bool = False,
    ) -> None:
        current = self.task_count(user_id, project_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO personalization_suppressions VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, project_key, field) DO UPDATE SET
                rejected_at_task=excluded.rejected_at_task,
                suppress_until_task=excluded.suppress_until_task,
                suppress_forever=excluded.suppress_forever,
                updated_at=excluded.updated_at""",
                (
                    user_id,
                    self._project(project_id),
                    field,
                    current,
                    current + cooldown_tasks,
                    int(forever),
                    utc_now(),
                ),
            )
            conn.commit()

    def can_propose(self, field: str, project_id: str | None, user_id: str = "local-user") -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM personalization_suppressions
                WHERE user_id=? AND project_key=? AND field=?""",
                (user_id, self._project(project_id), field),
            ).fetchone()
        if row is None:
            return True
        return not bool(row["suppress_forever"]) and self.task_count(
            user_id, project_id
        ) >= int(row["suppress_until_task"])
