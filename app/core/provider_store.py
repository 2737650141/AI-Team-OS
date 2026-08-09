"""Persistent custom OpenAI-compatible providers; credentials live elsewhere."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.memory.models import utc_now


class CustomProvider(BaseModel):
    provider_id: str
    provider_name: str
    base_url: str
    models_endpoint: str = "/models"
    chat_endpoint: str = "/chat/completions"
    api_mode: str = "openai_compatible"
    default_model: str = ""
    role_models: dict[str, str] = Field(default_factory=dict)
    discovered_models: list[dict[str, Any]] = Field(default_factory=list)
    configured: bool = False
    storage: str = "missing"
    health: str = "not_tested"
    discovery_status: str = "not_synced"
    invocation_status: str = "not_tested"
    last_checked_at: str | None = None
    last_model_sync_at: str | None = None
    last_invoked_at: str | None = None
    is_default: bool = False
    local_provider: bool = False
    test_provider: bool = False
    created_at: str
    updated_at: str


class ProviderStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS custom_providers (
                    provider_id TEXT PRIMARY KEY,
                    provider_name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    models_endpoint TEXT NOT NULL,
                    chat_endpoint TEXT NOT NULL,
                    api_mode TEXT NOT NULL,
                    default_model TEXT NOT NULL,
                    role_models_json TEXT NOT NULL,
                    discovered_models_json TEXT NOT NULL,
                    health TEXT NOT NULL,
                    discovery_status TEXT NOT NULL,
                    invocation_status TEXT NOT NULL DEFAULT 'not_tested',
                    last_checked_at TEXT,
                    last_model_sync_at TEXT,
                    last_invoked_at TEXT,
                    is_default INTEGER NOT NULL,
                    local_provider INTEGER NOT NULL,
                    test_provider INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_provider_name
                    ON custom_providers(provider_name COLLATE NOCASE);
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(custom_providers)")}
            if "invocation_status" not in columns:
                conn.execute(
                    "ALTER TABLE custom_providers ADD COLUMN invocation_status "
                    "TEXT NOT NULL DEFAULT 'not_tested'"
                )
            if "last_invoked_at" not in columns:
                conn.execute("ALTER TABLE custom_providers ADD COLUMN last_invoked_at TEXT")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def secret_key(provider_id: str) -> str:
        return f"custom_provider.{provider_id}.api_key"

    def create(self, **values: Any) -> CustomProvider:
        now = utc_now()
        provider = CustomProvider(
            provider_id=f"cp_{uuid.uuid4().hex[:16]}",
            created_at=now,
            updated_at=now,
            **values,
        )
        with self._lock, self._connect() as conn:
            if provider.is_default:
                conn.execute("UPDATE custom_providers SET is_default=0")
            conn.execute(
                """INSERT INTO custom_providers
                (provider_id, provider_name, base_url, models_endpoint, chat_endpoint,
                api_mode, default_model, role_models_json, discovered_models_json,
                health, discovery_status, invocation_status, last_checked_at,
                last_model_sync_at, last_invoked_at, is_default, local_provider,
                test_provider, created_at, updated_at) VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                self._values(provider),
            )
            conn.commit()
        return provider

    def update(self, provider_id: str, **updates: Any) -> CustomProvider:
        existing = self.get(provider_id)
        if existing is None:
            raise KeyError(provider_id)
        allowed = {
            "provider_name",
            "base_url",
            "models_endpoint",
            "chat_endpoint",
            "api_mode",
            "default_model",
            "role_models",
            "health",
            "discovery_status",
            "invocation_status",
            "last_checked_at",
            "last_model_sync_at",
            "last_invoked_at",
            "is_default",
            "local_provider",
            "test_provider",
            "discovered_models",
        }
        safe_updates = {key: value for key, value in updates.items() if key in allowed}
        provider = existing.model_copy(update={**safe_updates, "updated_at": utc_now()})
        with self._lock, self._connect() as conn:
            if provider.is_default:
                conn.execute(
                    "UPDATE custom_providers SET is_default=0 WHERE provider_id<>?",
                    (provider_id,),
                )
            conn.execute(
                """UPDATE custom_providers SET provider_name=?, base_url=?, models_endpoint=?,
                chat_endpoint=?, api_mode=?, default_model=?, role_models_json=?,
                discovered_models_json=?, health=?, discovery_status=?, invocation_status=?,
                last_checked_at=?, last_model_sync_at=?, last_invoked_at=?,
                is_default=?, local_provider=?, test_provider=?,
                updated_at=? WHERE provider_id=?""",
                (
                    provider.provider_name,
                    provider.base_url,
                    provider.models_endpoint,
                    provider.chat_endpoint,
                    provider.api_mode,
                    provider.default_model,
                    json.dumps(provider.role_models, ensure_ascii=False),
                    json.dumps(provider.discovered_models, ensure_ascii=False),
                    provider.health,
                    provider.discovery_status,
                    provider.invocation_status,
                    provider.last_checked_at,
                    provider.last_model_sync_at,
                    provider.last_invoked_at,
                    int(provider.is_default),
                    int(provider.local_provider),
                    int(provider.test_provider),
                    provider.updated_at,
                    provider_id,
                ),
            )
            conn.commit()
        return provider

    def update_discovery(
        self, provider_id: str, models: list[dict[str, Any]], status: str
    ) -> CustomProvider:
        return self.update(
            provider_id,
            discovered_models=models,
            discovery_status=status,
            last_model_sync_at=utc_now(),
        )

    def get(self, provider_id: str) -> CustomProvider | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM custom_providers WHERE provider_id=?", (provider_id,)
            ).fetchone()
        return self._provider(row) if row else None

    def list(self) -> list[CustomProvider]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM custom_providers ORDER BY is_default DESC, provider_name"
            ).fetchall()
        return [self._provider(row) for row in rows]

    def default(self) -> CustomProvider | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM custom_providers WHERE is_default=1 LIMIT 1"
            ).fetchone()
        return self._provider(row) if row else None

    def delete(self, provider_id: str) -> None:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM custom_providers WHERE provider_id=?", (provider_id,))
            if not cur.rowcount:
                raise KeyError(provider_id)
            conn.commit()

    @staticmethod
    def _values(provider: CustomProvider) -> tuple[Any, ...]:
        return (
            provider.provider_id,
            provider.provider_name,
            provider.base_url,
            provider.models_endpoint,
            provider.chat_endpoint,
            provider.api_mode,
            provider.default_model,
            json.dumps(provider.role_models, ensure_ascii=False),
            json.dumps(provider.discovered_models, ensure_ascii=False),
            provider.health,
            provider.discovery_status,
            provider.invocation_status,
            provider.last_checked_at,
            provider.last_model_sync_at,
            provider.last_invoked_at,
            int(provider.is_default),
            int(provider.local_provider),
            int(provider.test_provider),
            provider.created_at,
            provider.updated_at,
        )

    @staticmethod
    def _provider(row: sqlite3.Row) -> CustomProvider:
        data = dict(row)
        data["role_models"] = json.loads(data.pop("role_models_json") or "{}")
        data["discovered_models"] = json.loads(data.pop("discovered_models_json") or "[]")
        data["is_default"] = bool(data["is_default"])
        data["local_provider"] = bool(data["local_provider"])
        data["test_provider"] = bool(data["test_provider"])
        return CustomProvider(**data)


def models_url(base_url: str, endpoint: str) -> str:
    """Join without producing duplicate `/v1/v1/models` paths."""

    base_url = base_url.rstrip("/")
    scheme_at = base_url.find("://")
    path_at = base_url.find("/", scheme_at + 3)
    if path_at < 0:
        origin, base_path = base_url, ""
    else:
        origin, base_path = base_url[:path_at], base_url[path_at:]
    endpoint_path = "/" + endpoint.strip().lstrip("/")
    base_path = base_path.rstrip("/")
    if base_path and endpoint_path.startswith(base_path + "/"):
        path = endpoint_path
    else:
        path = f"{base_path}{endpoint_path}"
    return f"{origin}{path}"


def normalize_models(payload: Any) -> list[dict[str, Any]]:
    """Normalize common OpenAI-compatible model list shapes."""

    raw = payload
    if isinstance(payload, dict):
        raw = payload.get("data", payload.get("models", []))
    if not isinstance(raw, list):
        return []
    models: dict[str, dict[str, Any]] = {}
    for item in raw:
        if isinstance(item, str):
            model_id = item
            meta: dict[str, Any] = {"id": model_id}
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "").strip()
            meta = {"id": model_id}
            for field in ("owned_by", "created"):
                if field in item and isinstance(item[field], (str, int, float)):
                    meta[field] = item[field]
        else:
            continue
        if model_id:
            models[model_id] = meta
    return [models[key] for key in sorted(models, key=str.casefold)]
