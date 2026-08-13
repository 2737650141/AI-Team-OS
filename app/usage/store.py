from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.usage.models import ModelCapability, NormalizedModelUsage, utc_now

_USAGE_COLUMNS = tuple(NormalizedModelUsage.model_fields)


class UsageStore:
    """Privacy-minimal SQLite telemetry store. No prompt or response content is accepted."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "runtime" / "usage" / "usage.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_usage (
                    usage_id TEXT PRIMARY KEY, scope TEXT NOT NULL DEFAULT 'user_task',
                    task_id TEXT NOT NULL, run_id TEXT,
                    call_id TEXT NOT NULL UNIQUE, role TEXT NOT NULL, agent_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL, provider_name TEXT NOT NULL, model_id TEXT NOT NULL,
                    input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER,
                    cached_input_tokens INTEGER, cache_write_tokens INTEGER, other_tokens INTEGER,
                    total_tokens INTEGER, usage_source TEXT NOT NULL,
                    estimated_input_tokens INTEGER, estimated_output_tokens INTEGER,
                    context_tokens_before INTEGER, context_tokens_after INTEGER,
                    context_limit INTEGER,
                    compression_triggered INTEGER NOT NULL DEFAULT 0,
                    compression_tokens_before INTEGER, compression_tokens_after INTEGER,
                    latency_ms INTEGER, cost_input REAL, cost_output REAL, cost_total REAL,
                    currency TEXT, cost_source TEXT NOT NULL, timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usage_task ON model_usage(task_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_usage_run ON model_usage(run_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON model_usage(timestamp);
                CREATE TABLE IF NOT EXISTS model_capabilities (
                    provider_id TEXT NOT NULL, model_id TEXT NOT NULL, context_window INTEGER,
                    max_output_tokens INTEGER, tokenizer TEXT, usage_reporting INTEGER,
                    reasoning_usage_reporting INTEGER, cache_usage_reporting INTEGER,
                    source TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(provider_id, model_id)
                );
                CREATE TABLE IF NOT EXISTS usage_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS context_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT,
                    role TEXT NOT NULL, model TEXT NOT NULL, checkpoint_json TEXT NOT NULL,
                    before_tokens INTEGER NOT NULL, after_tokens INTEGER NOT NULL,
                    freed_tokens INTEGER NOT NULL, duration_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO usage_settings(key, value, updated_at)
                    VALUES ('retention_days', '30', CURRENT_TIMESTAMP);
                INSERT OR IGNORE INTO schema_migrations(version, applied_at)
                    VALUES (1, CURRENT_TIMESTAMP);
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(model_usage)")}
            if "scope" not in columns:
                conn.execute(
                    "ALTER TABLE model_usage ADD COLUMN scope TEXT NOT NULL DEFAULT 'user_task'"
                )

    def record_checkpoint(
        self, checkpoint, metrics: dict[str, Any], *, role: str, model: str
    ) -> None:
        payload = checkpoint.model_dump(mode="json")
        # This is a structured state checkpoint, never message history or hidden reasoning.
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO context_checkpoints
                (checkpoint_id,task_id,run_id,role,model,checkpoint_json,before_tokens,
                 after_tokens,freed_tokens,duration_ms,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    checkpoint.checkpoint_id,
                    checkpoint.task_id,
                    checkpoint.run_id,
                    role,
                    model,
                    json.dumps(payload, ensure_ascii=False),
                    metrics["before"],
                    metrics["after"],
                    metrics["freed"],
                    metrics["duration_ms"],
                    checkpoint.created_at,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, usage: NormalizedModelUsage) -> None:
        data = usage.model_dump(mode="json")
        values = [int(value) if isinstance(value, bool) else value for value in data.values()]
        marks = ",".join("?" for _ in _USAGE_COLUMNS)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO model_usage ({','.join(_USAGE_COLUMNS)}) VALUES ({marks})",
                values,
            )

    def set_scope(self, task_id: str, scope: str) -> int:
        if scope not in {"user_task", "conversation", "diagnostic", "system"}:
            raise ValueError("invalid usage scope")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE model_usage SET scope=? WHERE task_id=?", (scope, task_id)
            )
            return max(0, cursor.rowcount)

    def set_capability(self, capability: ModelCapability) -> None:
        data = capability.model_dump(mode="json")
        for key in ("usage_reporting", "reasoning_usage_reporting", "cache_usage_reporting"):
            if data[key] is not None:
                data[key] = int(data[key])
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO model_capabilities
                (provider_id,model_id,context_window,max_output_tokens,tokenizer,usage_reporting,
                 reasoning_usage_reporting,cache_usage_reporting,source,updated_at)
                VALUES (:provider_id,:model_id,:context_window,:max_output_tokens,:tokenizer,
                 :usage_reporting,:reasoning_usage_reporting,:cache_usage_reporting,:source,:updated_at)""",
                data,
            )

    def capability(self, provider_id: str, model_id: str) -> ModelCapability | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_capabilities WHERE provider_id=? AND model_id=?",
                (provider_id, model_id),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        for key in ("usage_reporting", "reasoning_usage_reporting", "cache_usage_reporting"):
            data[key] = None if data[key] is None else bool(data[key])
        return ModelCapability.model_validate(data)

    def retention_days(self) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM usage_settings WHERE key='retention_days'"
            ).fetchone()
        return None if not row or row[0] == "forever" else int(row[0])

    def set_retention(self, value: int | None) -> None:
        if value not in {7, 30, 90, None}:
            raise ValueError("retention must be 7, 30, 90, or forever")
        stored = "forever" if value is None else str(value)
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO usage_settings(key,value,updated_at)
                VALUES ('retention_days',?,?)""",
                (stored, utc_now()),
            )
        self.prune()

    def prune(self, now: datetime | None = None) -> int:
        days = self.retention_days()
        if days is None:
            return 0
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM model_usage WHERE timestamp < ?", (cutoff.isoformat(),)
            )
            return max(0, cursor.rowcount)

    def summary(
        self, *, run_id: str | None = None, task_id: str | None = None, days: int | None = 30
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id=?")
            params.append(run_id)
        if task_id:
            clauses.append("task_id=?")
            params.append(task_id)
        if days is not None:
            clauses.append("timestamp>=?")
            params.append((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    f"SELECT * FROM model_usage {where} ORDER BY timestamp", params
                ).fetchall()
            ]
        return _summarize(rows)


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "has_data": False,
            "requests": 0,
            "total_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "cached_input_tokens": None,
            "cache_write_tokens": None,
            "other_tokens": None,
            "cost_total": None,
            "currency": None,
            "cache_hit_rate": None,
            "runtime_ms": None,
            "average_latency_ms": None,
            "usage_source": "UNAVAILABLE",
            "last_compression": None,
            "current_context": None,
            "by_agent": [],
            "by_model": [],
            "by_provider": [],
            "by_task": [],
            "timeline": [],
        }

    def summed(key: str) -> int | None:
        vals = [row[key] for row in rows if row[key] is not None]
        return sum(vals) if vals else None

    costs = [row["cost_total"] for row in rows if row["cost_total"] is not None]
    latencies = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
    cached_rows = [
        row
        for row in rows
        if row["cached_input_tokens"] is not None and row["input_tokens"] is not None
    ]
    eligible = sum(row["input_tokens"] for row in cached_rows)
    cache_hit = (
        (sum(row["cached_input_tokens"] for row in cached_rows) / eligible)
        if eligible
        else (0.0 if cached_rows else None)
    )
    parsed = [datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) for row in rows]
    runtime_ms = (
        max(0, int((max(parsed) - min(parsed)).total_seconds() * 1000))
        if len(rows) > 1
        else rows[0]["latency_ms"]
    )

    def group(key: str) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = row[key] or "unknown"
            item = grouped.setdefault(
                name,
                {
                    "name": name,
                    "requests": 0,
                    "tokens": 0,
                    "latency_ms": 0,
                    "cost": 0.0,
                    "cost_available": True,
                },
            )
            item["requests"] += 1
            item["tokens"] += row["total_tokens"] or 0
            item["latency_ms"] += row["latency_ms"] or 0
            if row["cost_total"] is None:
                item["cost_available"] = False
            else:
                item["cost"] += row["cost_total"]
        return sorted(grouped.values(), key=lambda item: item["tokens"], reverse=True)

    latest_context = next(
        (row for row in reversed(rows) if row["context_tokens_after"] is not None), None
    )
    sources = {row["usage_source"] for row in rows}
    aggregate_source = (
        "UNAVAILABLE"
        if sources == {"UNAVAILABLE"}
        else "ESTIMATED"
        if "ESTIMATED" in sources or "UNAVAILABLE" in sources
        else "REPORTED"
    )
    compressed = next((row for row in reversed(rows) if row["compression_triggered"]), None)
    return {
        "has_data": True,
        "requests": len(rows),
        "total_tokens": summed("total_tokens"),
        "input_tokens": summed("input_tokens"),
        "output_tokens": summed("output_tokens"),
        "reasoning_tokens": summed("reasoning_tokens"),
        "cached_input_tokens": summed("cached_input_tokens"),
        "cache_write_tokens": summed("cache_write_tokens"),
        "other_tokens": summed("other_tokens"),
        "cost_total": sum(costs) if len(costs) == len(rows) else None,
        "currency": rows[0]["currency"] if costs else None,
        "cache_hit_rate": cache_hit,
        "runtime_ms": runtime_ms,
        "average_latency_ms": int(sum(latencies) / len(latencies)) if latencies else None,
        "usage_source": aggregate_source,
        "current_context": latest_context,
        "last_compression": (
            {
                "before_tokens": compressed["compression_tokens_before"],
                "after_tokens": compressed["compression_tokens_after"],
                "freed_tokens": (
                    compressed["compression_tokens_before"]
                    - compressed["compression_tokens_after"]
                    if compressed["compression_tokens_before"] is not None
                    and compressed["compression_tokens_after"] is not None
                    else None
                ),
                "timestamp": compressed["timestamp"],
            }
            if compressed
            else None
        ),
        "by_agent": group("agent_id"),
        "by_model": group("model_id"),
        "by_provider": group("provider_name"),
        "by_task": group("task_id"),
        "timeline": [
            {
                "timestamp": row["timestamp"],
                "scope": row["scope"],
                "agent": row["agent_id"],
                "model": row["model_id"],
                "tokens": row["total_tokens"],
                "source": row["usage_source"],
                "compression_triggered": bool(row["compression_triggered"]),
                "compression_tokens_before": row["compression_tokens_before"],
                "compression_tokens_after": row["compression_tokens_after"],
            }
            for row in rows[-100:]
        ],
    }
