"""M7-A4C: proactive notification / result delivery.

Windows-Toasts owns the desktop transport. AI Team OS owns deterministic
policy, notification keys, durable dedup markers, bounded message bodies, and
the small delivery adapter. This module is not an LLM-callable tool.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

NOTIFY = "NOTIFY"
SILENT = "SILENT"
_ONE_TIME_NOTIFY = ("COMPLETED", "FAILED")
_ONE_TIME_EVENT = "notification_delivered"


def policy_decision(kind: str, status: str | None = None) -> str:
    """Deterministic notification policy; silent unless explicitly eligible."""
    if kind == "one_time":
        return NOTIFY if status in _ONE_TIME_NOTIFY else SILENT
    if kind == "condition":
        return NOTIFY if status == "CONDITION_TRIGGERED" else SILENT
    return SILENT


def notification_key(
    kind: str, job_id: str, status: str, fingerprint: str = "", run_id: str = ""
) -> str:
    """Return the stable dedup key for a condition or one-time outcome."""
    if kind == "condition":
        blob = f"{job_id}|condition|{fingerprint}"
    else:
        blob = f"{job_id}|one_time|{run_id}|{status}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _marker_payload(key: str, job_id: str, run_id: str, kind: str) -> dict[str, str]:
    return {
        "notification_key": key,
        "job_id": job_id,
        "run_id": run_id or "",
        "kind": kind,
        "delivered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def mark_delivered_condition(job_id: str, fingerprint: str, data_dir: str = "data") -> None:
    """Persist the notification marker separately from A4B's baseline."""
    from app.background.jobs import get_scheduler

    try:
        scheduler = get_scheduler(data_dir)
        job = scheduler.get_job(job_id)
        if job is None:
            # Isolated notification-key tests may not register a scheduler
            # job. The dispatcher itself validates the production source job.
            return
        kwargs = dict(job.kwargs or {})
        kwargs["last_notified_fingerprint"] = fingerprint
        scheduler.modify_job(job_id, kwargs=kwargs)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 — marker persistence is critical
        raise RuntimeError(f"condition notification marker persistence failed: {job_id}") from exc


def last_notified_condition(job_id: str, data_dir: str = "data") -> str:
    """Read the persisted condition delivery marker."""
    from app.background.jobs import get_scheduler

    try:
        job = get_scheduler(data_dir).get_job(job_id)
    except Exception as exc:  # noqa: BLE001 — marker read errors are critical
        raise RuntimeError(f"condition notification marker read failed: {job_id}") from exc
    if job is None or not job.kwargs:
        return ""
    return str(job.kwargs.get("last_notified_fingerprint", "") or "")


def one_time_delivered(key: str, data_dir: str = "data") -> bool:
    """Return whether the durable one-time marker exists."""
    db = Path(str(data_dir)) / "runtime" / "events.sqlite"
    if not db.exists():
        return False
    try:
        with sqlite3.connect(str(db)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type=? AND payload_safe LIKE ?",
                (_ONE_TIME_EVENT, f"%{key}%"),
            ).fetchone()
        return bool(row and row[0] > 0)
    except Exception as exc:  # noqa: BLE001 — marker read errors are critical
        raise RuntimeError(f"one-time notification marker read failed: {key}") from exc


def mark_delivered_one_time(
    key: str, job_id: str, run_id: str, data_dir: str = "data"
) -> None:
    """Persist the one-time marker using the existing event-store seam.

    The event type is A4C-local. The existing event store may reject unknown
    types, so the direct SQLite fallback is retained. If both paths fail, the
    marker error is raised instead of being silently discarded.
    """
    from app.core.events import emit as event_emit
    from app.core.events import init as events_init

    try:
        events_init(Path(str(data_dir)))
        event_emit(
            task_id=f"bg-{job_id}",
            run_id=run_id or f"bg-{job_id}",
            event_type=_ONE_TIME_EVENT,
            actor_type="background",
            actor_id="notification",
            summary="notification delivered",
            payload_safe=_marker_payload(key, job_id, run_id, "one_time"),
        )
        return
    except Exception:  # noqa: BLE001 — use the existing seam first
        logger.debug("event store marker path unavailable; using direct fallback", exc_info=True)
        try:
            db = Path(str(data_dir)) / "runtime" / "events.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(db)) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS events ("
                    " event_id TEXT, task_id TEXT, run_id TEXT, timestamp TEXT,"
                    " sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT,"
                    " actor_type TEXT, actor_id TEXT, summary TEXT, payload_safe TEXT)"
                )
                import json

                conn.execute(
                    "INSERT INTO events (event_id, task_id, run_id, timestamp, event_type,"
                    " actor_type, actor_id, summary, payload_safe) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        hashlib.sha256(key.encode()).hexdigest()[:16],
                        f"bg-{job_id}",
                        run_id or f"bg-{job_id}",
                        datetime.now(timezone.utc).isoformat(),
                        _ONE_TIME_EVENT,
                        "background",
                        "notification",
                        "notification delivered",
                        json.dumps(_marker_payload(key, job_id, run_id, "one_time")),
                    ),
                )
            return
        except Exception as fallback_error:  # noqa: BLE001 — fail loud
            message = f"one-time notification marker persistence failed: {key}"
            raise RuntimeError(message) from fallback_error


def send_notification(
    title: str,
    body: str,
    notification_key_value: str,
    job_id: str,
    run_id: str = "",
    kind: str = "one_time",
    data_dir: str = "data",
    dedup_marker: str = "",
) -> str:
    """Send one toast and then persist its durable dedup marker.

    Toast transport failures return ``DELIVERY_FAILED``. Marker persistence
    failures raise so the caller can report the infrastructure problem; the
    dispatcher handles that notification error without changing task outcome.
    """
    if kind == "condition":
        if dedup_marker and last_notified_condition(job_id, data_dir) == dedup_marker:
            return "SUPPRESSED_DUPLICATE"
    elif one_time_delivered(notification_key_value, data_dir):
        return "SUPPRESSED_DUPLICATE"

    try:
        from windows_toasts import Toast, ToastDuration, WindowsToaster

        toaster = WindowsToaster("AI Team OS")
        toast = Toast()
        toast.text_fields = [str(title)[:120], str(body)[:200]]
        toast.duration = ToastDuration.Short
        toaster.show_toast(toast)
    except Exception:  # noqa: BLE001 — wheel failure is a delivery failure
        return "DELIVERY_FAILED"

    if kind == "condition":
        mark_delivered_condition(job_id, dedup_marker, data_dir)
    else:
        mark_delivered_one_time(notification_key_value, job_id, run_id, data_dir)
    return "DELIVERED"


def safe_excerpt(text: str, limit: int = 120) -> str:
    """Bounded single-line notification body excerpt."""
    if not text:
        return ""
    return " ".join(str(text).split())[:limit]
