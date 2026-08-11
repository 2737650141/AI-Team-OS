from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.voice.models import VoiceSettings


class VoiceMetadataStore:
    """Settings and safe event metadata only; audio and transcripts are prohibited."""

    _ALLOWED_EVENT_KEYS = {
        "state",
        "action",
        "error_code",
        "duration_ms",
        "task_id",
        "asr_ms",
        "wake_attempts",
        "false_activation",
        "miss",
    }

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS voice_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS voice_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT NOT NULL,
                    metadata TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=10)

    def settings(self) -> VoiceSettings:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM voice_settings WHERE id = 1").fetchone()
        return VoiceSettings.model_validate_json(row[0]) if row else VoiceSettings()

    def save_settings(self, settings: VoiceSettings) -> VoiceSettings:
        payload = settings.model_dump_json()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO voice_settings(id, payload) VALUES(1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (payload,),
            )
        return settings

    def event(self, event_type: str, metadata: dict[str, Any]) -> None:
        safe = {key: value for key, value in metadata.items() if key in self._ALLOWED_EVENT_KEYS}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO voice_events(event_type, metadata) VALUES(?, ?)",
                (event_type, json.dumps(safe, ensure_ascii=True)),
            )


class VoiceEventStore(VoiceMetadataStore):
    """Named governance boundary for safe voice events."""
