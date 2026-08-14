"""Small, durable task-control mailbox for UX steering.

The mailbox does not execute work and cannot bypass approvals. Graph nodes only
inspect it at safe node boundaries, preserving checkpoints and completed work.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class TaskControlStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "runtime" / "task_controls"
        self._lock = threading.RLock()

    def _path(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("invalid run id")
        return self.root / f"{run_id}.json"

    def snapshot(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        with self._lock:
            if not path.exists():
                return {"run_id": run_id, "action": None, "constraints": []}
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                return {"run_id": run_id, "action": None, "constraints": []}
        return {
            "run_id": run_id,
            "action": data.get("action"),
            "constraints": list(data.get("constraints") or [])[-10:],
            "updated_at": data.get("updated_at"),
        }

    def request(self, run_id: str, action: Literal["pause", "stop"]) -> dict[str, Any]:
        data = self.snapshot(run_id)
        data["action"] = action
        return self._write(run_id, data)

    def add_constraint(self, run_id: str, instruction: str) -> dict[str, Any]:
        data = self.snapshot(run_id)
        constraints = list(data.get("constraints") or [])
        if instruction not in constraints:
            constraints.append(instruction[:2000])
        data["constraints"] = constraints[-10:]
        return self._write(run_id, data)

    def clear_action(self, run_id: str) -> dict[str, Any]:
        data = self.snapshot(run_id)
        data["action"] = None
        return self._write(run_id, data)

    def take_constraints(self, run_id: str) -> list[str]:
        data = self.snapshot(run_id)
        constraints = list(data.get("constraints") or [])
        if constraints:
            data["constraints"] = []
            self._write(run_id, data)
        return constraints

    def _write(self, run_id: str, data: dict[str, Any]) -> dict[str, Any]:
        path = self._path(run_id)
        data = {
            "run_id": run_id,
            "action": data.get("action"),
            "constraints": list(data.get("constraints") or [])[-10:],
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        return data
