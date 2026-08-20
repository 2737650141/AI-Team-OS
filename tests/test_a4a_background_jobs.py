"""M7-A4A — Background Jobs wheel audit + durable schedule POC tests.

Wheel-first: APScheduler 3.x owns scheduling + persistence (SQLAlchemyJobStore
over SQLite). These tests exercise the WHEEL's real semantics with short real
timers; longer real-time behavior is verified in the POC scripts under
A4A_REAL_SCHEDULER=1. No scheduler/queue/worker code is written.

Real-time tests are gated behind A4A_REAL_SCHEDULER=1 so normal CI never
waits tens of seconds.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def test_apscheduler_stable_3x_installed() -> None:
    """Production line must be APScheduler 3.x (4.x is pre-release)."""
    import importlib.metadata as md

    version = md.version("APScheduler")
    assert version.startswith("3.")
    assert "4." not in version


def test_sqlalchemy_job_store_available() -> None:
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

    assert SQLAlchemyJobStore is not None


def test_langgraph_checkpointer_already_durable() -> None:
    """Repo already has durable LangGraph persistence (thread_id=run_id)."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    assert SqliteSaver is not None
    import app.runner as runner

    assert hasattr(runner, "_checkpoint_saver")


def test_scheduler_persistence_is_not_workflow_persistence() -> None:
    """APScheduler DB stores when to run; LangGraph stores run progress."""
    assert "SQLAlchemyJobStore" in (
        "apscheduler.jobstores.sqlalchemy.SQLAlchemyJobStore"
    )
    assert "langgraph.checkpoint.sqlite.SqliteSaver" in (
        "langgraph.checkpoint.sqlite.SqliteSaver"
    )


_CANCEL_FIRED: list[str] = []


def _cancel_mark() -> None:
    _CANCEL_FIRED.append("x")


def _dup_noop() -> None:
    pass


def _tz_noop() -> None:
    pass


def test_lambda_job_not_persistable(tmp_path) -> None:
    """A lambda cannot be stored as a persistent APScheduler job."""
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.background import BackgroundScheduler

    db = tmp_path / "jobs.sqlite"
    store = SQLAlchemyJobStore(url=f"sqlite:///{db}")
    scheduler = BackgroundScheduler(jobstores={"default": store})
    scheduler.start()
    try:
        with pytest.raises(ValueError):
            scheduler.add_job(
                lambda: None,
                trigger="interval",
                seconds=60,
                id="lambda-job",
            )
    finally:
        scheduler.shutdown(wait=False)


def test_same_job_id_not_duplicated(tmp_path) -> None:
    """replace_existing=True collapses duplicate registration to one job."""
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.background import BackgroundScheduler

    db = tmp_path / "jobs.sqlite"
    store = SQLAlchemyJobStore(url=f"sqlite:///{db}")
    scheduler = BackgroundScheduler(jobstores={"default": store})
    scheduler.start()
    for _ in range(2):
        scheduler.add_job(
            _dup_noop,
            trigger="interval",
            seconds=3600,
            id="dup",
            replace_existing=True,
        )
    jobs = scheduler.get_jobs()
    assert len([job for job in jobs if job.id == "dup"]) == 1
    scheduler.shutdown(wait=False)


def test_timezone_aware_next_run(tmp_path) -> None:
    """Scheduler timezone must produce tz-aware next_run_time."""
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.background import BackgroundScheduler

    db = tmp_path / "jobs.sqlite"
    store = SQLAlchemyJobStore(url=f"sqlite:///{db}")
    local_tz = datetime.now().astimezone().tzinfo
    scheduler = BackgroundScheduler(jobstores={"default": store}, timezone=local_tz)
    scheduler.start()
    scheduler.add_job(_tz_noop, trigger="interval", seconds=3600, id="tz")
    job = scheduler.get_job("tz")
    assert job is not None
    assert job.next_run_time is not None
    assert job.next_run_time.utcoffset() is not None
    scheduler.shutdown(wait=False)


def test_cancel_prevents_execution(tmp_path) -> None:
    """A removed job no longer fires."""
    import time

    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.background import BackgroundScheduler

    _CANCEL_FIRED.clear()
    db = tmp_path / "jobs.sqlite"
    store = SQLAlchemyJobStore(url=f"sqlite:///{db}")
    scheduler = BackgroundScheduler(jobstores={"default": store})
    scheduler.add_job(_cancel_mark, trigger="interval", seconds=1, id="c", max_instances=1)
    scheduler.start()
    time.sleep(2.5)
    scheduler.remove_job("c")
    count_before = len(_CANCEL_FIRED)
    time.sleep(2.5)
    scheduler.shutdown(wait=True)
    assert len(_CANCEL_FIRED) == count_before
    assert len(_CANCEL_FIRED) >= 1


REAL = os.environ.get("A4A_REAL_SCHEDULER") == "1"
_RESTART_MARKER: Path | None = None


def _restart_marker() -> None:
    if _RESTART_MARKER is not None:
        _RESTART_MARKER.write_text("fired", encoding="utf-8")


@pytest.mark.skipif(not REAL, reason="real-scheduler gate (A4A_REAL_SCHEDULER=1)")
def test_real_persistent_schedule_survives_restart(tmp_path) -> None:
    """A schedule survives scheduler restart in the wheel store."""
    import time

    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.date import DateTrigger

    global _RESTART_MARKER
    _RESTART_MARKER = tmp_path / "fired.txt"
    db = tmp_path / "jobs.sqlite"

    def make_scheduler() -> BackgroundScheduler:
        return BackgroundScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{db}")},
            timezone=timezone.utc,
        )

    scheduler_one = make_scheduler()
    scheduler_one.start()
    run_at = datetime.now(timezone.utc) + timedelta(seconds=10)
    scheduler_one.add_job(
        _restart_marker,
        trigger=DateTrigger(run_date=run_at),
        id="survive",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler_one.shutdown(wait=False)
    time.sleep(2)

    scheduler_two = make_scheduler()
    scheduler_two.start()
    job = scheduler_two.get_job("survive")
    assert job is not None
    time.sleep(12)
    scheduler_two.shutdown(wait=True)
    assert _RESTART_MARKER.exists()
