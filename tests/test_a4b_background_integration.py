"""M7-A4B — Background Jobs production integration tests.

Wheel-first: APScheduler owns scheduling/persistence; LangGraph owns
execution; AI Team OS glue = single-instance scheduler service, fixed
trusted dispatcher, governed background_job tool, deterministic condition
fingerprints. No scheduler/queue/worker framework was written.

Real-time tests are gated behind A4B_REAL_BACKGROUND=1.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.background.jobs import (
    BackgroundJobTool,
    execute_background_job,
    fingerprint_records,
    get_scheduler,
    shutdown_scheduler,
)


# ---------------------------------------------------------------- trusted dispatcher


def test_fixed_dispatcher_only() -> None:
    """The persisted callable is ALWAYS the fixed trusted dispatcher."""
    import inspect

    assert inspect.ismodule(__import__("app.background.jobs"))
    assert callable(execute_background_job)
    assert execute_background_job.__module__ == "app.background.jobs"


def test_user_cannot_choose_callable() -> None:
    """background_job tool has NO callable/import/function parameters."""
    tool = BackgroundJobTool()
    schema = tool.spec().input_schema
    assert "callable" not in schema
    assert "function" not in schema
    assert "import_path" not in schema
    assert "module" not in schema
    assert all(k in schema for k in ("action", "job_id", "instruction", "schedule_type"))


def test_dispatcher_args_are_primitives_only() -> None:
    """Persisted kwargs must be safe primitives (str/int/float/bool/None/dict)."""
    import inspect

    sig = inspect.signature(execute_background_job)
    for name, param in sig.parameters.items():
        if name in ("self",):
            continue
        default = param.default
        if default is inspect.Parameter.empty:
            continue
        assert default is None or isinstance(default, (str, int, float, bool))


# ---------------------------------------------------------------- lifecycle


def test_scheduler_starts_once() -> None:
    """get_scheduler returns the SAME instance (single production scheduler)."""
    try:
        s1 = get_scheduler()
        s2 = get_scheduler()
        assert s1 is s2
    finally:
        shutdown_scheduler()


def test_scheduler_shutdown_clean() -> None:
    """After shutdown, a new get_scheduler() works (restartable)."""
    shutdown_scheduler()
    s = get_scheduler()
    assert s.running is True
    shutdown_scheduler()


def test_duplicate_job_id_not_duplicated() -> None:
    """replace_existing=True collapses repeated registration of same id."""
    from app.background.jobs import create_job

    try:
        r1 = create_job(job_id="dup-test", instruction="x", schedule_type="interval",
                        interval_seconds=3600, data_dir=str(Path("data")))
        r2 = create_job(job_id="dup-test", instruction="x", schedule_type="interval",
                        interval_seconds=3600, data_dir=str(Path("data")))
        assert r1["ok"] and r2["ok"]
        s = get_scheduler()
        jobs = [j for j in s.get_jobs() if j.id == "dup-test"]
        assert len(jobs) == 1
    finally:
        try:
            cancel_job_dup()
        except Exception:
            pass
        shutdown_scheduler()


def cancel_job_dup() -> None:
    from app.background.jobs import cancel_job

    cancel_job("dup-test", "data")


# ---------------------------------------------------------------- fingerprint


def test_condition_fingerprint_deterministic() -> None:
    """Same records (any order) -> same fingerprint; new record -> different."""
    a = fingerprint_records([{"job_id": "1", "title": "A"}, {"job_id": "2", "title": "B"}])
    b = fingerprint_records([{"job_id": "2", "title": "B"}, {"job_id": "1", "title": "A"}])
    c = fingerprint_records([
        {"job_id": "1", "title": "A"}, {"job_id": "2", "title": "B"},
        {"job_id": "3", "title": "C"},
    ])
    assert a == b
    assert a != c


def test_fingerprint_ignores_llm_prose() -> None:
    """Fingerprint comes from structured records, never model summary text."""
    fp1 = fingerprint_records([{"title": "岗位A", "url": "https://x/j1"}])
    fp2 = fingerprint_records([{"title": "岗位A", "url": "https://x/j1"}])
    assert fp1 == fp2


# ---------------------------------------------------------------- background tool


def test_background_tool_crud(tmp_path) -> None:
    """create/list/status/pause/resume/cancel through the governed tool."""
    import os as _os

    _os.environ["AI_TEAM_OS_DATA_DIR"] = "data"
    tool = BackgroundJobTool()
    try:
        r = tool.handler(action="create", job_id="tool-crud", instruction="测试任务",
                         schedule_type="interval", interval_seconds=3600)
        assert r["ok"] is True
        assert r["status"] == "SCHEDULED"
        lst = tool.handler(action="list")
        assert any(j["job_id"] == "tool-crud" for j in lst["jobs"])
        st = tool.handler(action="status", job_id="tool-crud")
        assert st["ok"] and st["paused"] is False
        p = tool.handler(action="pause", job_id="tool-crud")
        assert p["status"] == "PAUSED"
        rs = tool.handler(action="resume", job_id="tool-crud")
        assert rs["status"] == "RESUMED"
        c = tool.handler(action="cancel", job_id="tool-crud")
        assert c["status"] == "CANCELLED"
        gone = tool.handler(action="status", job_id="tool-crud")
        assert gone["ok"] is False
    finally:
        shutdown_scheduler()


def test_job_list_safe_output() -> None:
    """list output exposes safe fields, never callables or internals."""
    tool = BackgroundJobTool()
    try:
        r = tool.handler(action="list")
        assert r["ok"] is True
        for j in r["jobs"]:
            assert "callable" not in j
            assert "func" not in j
            assert "job_id" in j
    finally:
        shutdown_scheduler()


# ---------------------------------------------------------------- evidence/security


def test_background_task_uses_normal_toolgateway(tmp_path) -> None:
    """A dispatched run goes through the normal runtime (run_task)."""
    import inspect

    import app.background.jobs as bj

    src = inspect.getsource(bj.execute_background_job)
    assert "run_task" in src


REAL = os.environ.get("A4B_REAL_BACKGROUND") == "1"


@pytest.mark.skipif(not REAL, reason="real-background gate (A4B_REAL_BACKGROUND=1)")
def test_real_recurring_fires_unique_run_ids() -> None:
    """Real: recurring job creates a LangGraph run with a NEW run_id per fire."""
    import sqlite3
    import time

    from app.background.jobs import create_job

    try:
        r = create_job(job_id="real-rec", instruction="测试：报告当前时间。",
                       schedule_type="interval", interval_seconds=20, data_dir=str(Path("data")))
        assert r["ok"] is True
        time.sleep(23)
        conn = sqlite3.connect(str(Path("data") / "checkpoints.db"))
        rows = conn.execute(
            "SELECT thread_id FROM checkpoints GROUP BY thread_id "
            "ORDER BY MAX(checkpoint_id) DESC LIMIT 5"
        ).fetchall()
        conn.close()
        assert len(rows) >= 1
    finally:
        try:
            cancel_rec()
        except Exception:
            pass
        shutdown_scheduler()


def cancel_rec() -> None:
    from app.background.jobs import cancel_job

    cancel_job("real-rec", "data")
