"""M7-A4A: Background Runtime Foundation.

Wheel-first scheduler lifecycle and SQLAlchemy-backed persistence only.
Semantic execution, condition watch, notification delivery, and the governed
background tool remain in the later background-jobs layer.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # type: ignore[import-untyped]
from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]

_schedulers: dict[str, BackgroundScheduler] = {}
_lock = threading.Lock()


def get_scheduler(data_dir: str | Path | None = None) -> BackgroundScheduler:
    """Return one persistent scheduler per data directory."""
    root = str(Path(str(data_dir)) if data_dir else Path("data"))
    with _lock:
        if root not in _schedulers:
            db_path = str(Path(root) / "jobs.sqlite")
            store = SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
            local_tz = datetime.now().astimezone().tzinfo
            scheduler = BackgroundScheduler(
                jobstores={"default": store},
                timezone=local_tz,
            )
            scheduler.start()
            _schedulers[root] = scheduler
        return _schedulers[root]


def shutdown_scheduler(data_dir: str | Path | None = None) -> None:
    """Gracefully stop and forget the scheduler for a data directory."""
    root = str(Path(str(data_dir)) if data_dir else Path("data"))
    with _lock:
        scheduler = _schedulers.pop(root, None)
        if scheduler is not None:
            try:
                scheduler.shutdown(wait=True)
            finally:
                pass
