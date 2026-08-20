"""M7-A4B-CLOSURE-2 — baseline chain and semantic run overlap guarantee.

GATE A: a condition job starting from last_fingerprint=None establishes a
baseline, persists it via job.modify, and survives scheduler restart.
GATE B: the fixed dispatcher is synchronous so max_instances=1 covers the
whole semantic run. Real gates are behind A4B_CLOSURE2_REAL=1.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.background.jobs import (
    _condition_check,
    execute_background_job,
    get_scheduler,
    shutdown_scheduler,
)


def test_dispatcher_execution_model_is_synchronous() -> None:
    """Dispatcher runs LangGraph to completion in the executor worker."""
    import inspect

    src = inspect.getsource(execute_background_job)
    assert "threading.Thread" not in src
    assert "run_task(" in src
    assert ".start()" not in src.replace("scheduler.start", "sched_start")


def test_dispatcher_returns_run_id_from_sync_run() -> None:
    """Dispatcher returns the completed run's run_id."""

    class _FakeState:
        tool_calls = []

    class _FakeReport:
        run_id = "abc123"

        def __init__(self):
            self.state = _FakeState()

    def _fake_run_task(**kw):
        return _FakeReport()

    import app.runner as runner

    original = runner.run_task
    runner.run_task = _fake_run_task
    try:
        rid = execute_background_job("t1", "x", "langgraph", "data", run_now=True)
        assert rid == "abc123"
    finally:
        runner.run_task = original


def test_condition_chain_no_preseed_local() -> None:
    """Local deterministic chain: None -> BASELINE -> same -> NO_CHANGE."""
    from app.background.jobs import create_job

    try:
        create_job(job_id="c2-local", instruction="x", schedule_type="interval",
                   interval_seconds=3600, data_dir="data", task_kind="condition")
        r1 = _condition_check("c2-local", _report(
            [{"JobAdId": 1, "JobAdName": "A", "url": "u1"}]), "", "data")
        assert r1 == "BASELINE_ESTABLISHED"
        job = get_scheduler().get_job("c2-local")
        fp = job.kwargs.get("last_fingerprint") if job and job.kwargs else None
        assert fp is not None, "baseline must be persisted"
        r2 = _condition_check("c2-local", _report(
            [{"JobAdId": 1, "JobAdName": "A", "url": "u1"}]), fp, "data")
        assert r2 == "NO_CHANGE"
        shutdown_scheduler()
        import time

        time.sleep(0.5)
        job2 = get_scheduler().get_job("c2-local")
        assert job2 is not None
        fp2 = job2.kwargs.get("last_fingerprint") if job2 and job2.kwargs else None
        assert fp2 == fp
    finally:
        _cleanup("c2-local")


def _report(records):
    import json

    class _TC:
        def __init__(self):
            self.tool = "web_crawl_extract"
            self.result_summary = json.dumps({"ok": True, "records": records})

    class _S:
        tool_calls = [_TC()]

    class _R:
        def __init__(self):
            self.state = _S()

    return _R()


def _cleanup(job_id: str) -> None:
    try:
        from app.background.jobs import cancel_job

        cancel_job(job_id, "data")
    except Exception:
        pass
    shutdown_scheduler()


REAL = os.environ.get("A4B_CLOSURE2_REAL") == "1"


@pytest.mark.skipif(not REAL, reason="real gate (A4B_CLOSURE2_REAL=1)")
def test_real_same_job_slow_run_never_overlaps() -> None:
    """Real: slow recurring job has at most one unfinished run."""
    import sqlite3
    import time

    from app.background.jobs import cancel_job, create_job
    from app.runner import status_task

    job_id = "cl2-overlap"
    try:
        create_job(job_id=job_id, instruction="总结一下我最近10分钟在电脑上做了什么。",
                   schedule_type="interval", interval_seconds=2, data_dir="data")
        time.sleep(13)
        conn = sqlite3.connect(str(Path("data") / "checkpoints.db"))
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()
        conn.close()
        threads = set()
        for (tid,) in rows:
            try:
                rep = status_task(tid, data_dir=Path("data"))
                if rep.state.project_id == "bg-" + job_id:
                    threads.add(tid)
            except Exception:
                pass
        unfinished = 0
        for tid in threads:
            rep = status_task(tid, data_dir=Path("data"))
            if rep.state.current_status not in ("completed", "failed", "passed"):
                unfinished += 1
        assert len(threads) >= 1
        assert unfinished <= 1
    finally:
        try:
            cancel_job(job_id, "data")
        except Exception:
            pass
        shutdown_scheduler()


@pytest.mark.skipif(not REAL, reason="real gate (A4B_CLOSURE2_REAL=1)")
def test_real_baseline_survives_restart_without_preseed() -> None:
    """Real: baseline survives restart without pre-seeding."""
    import time

    from app.background.jobs import cancel_job, create_job
    from app.runner import run_task

    job_id = "cl2-chain"
    try:
        try:
            cancel_job(job_id, "data")
        except Exception:
            pass
        create_job(job_id=job_id, instruction="检查北方华创公开招聘。",
                   schedule_type="interval", interval_seconds=3600,
                   data_dir="data", task_kind="condition")
        job = get_scheduler().get_job(job_id)
        assert job.kwargs.get("last_fingerprint") in (None, "")
        r1 = run_task(goal="检查北方华创公开招聘，列出当前岗位名称。",
                      token_budget=150000, cost_budget=0.4,
                      project_id="bg-" + job_id + "-r1", model_mode="real",
                      max_model_calls=15, routing_intent="EXPLICIT",
                      routing_mode="BALANCED")
        s1 = _condition_check(job_id, r1, "", "data")
        assert s1 == "BASELINE_ESTABLISHED"
        job = get_scheduler().get_job(job_id)
        fp_a = job.kwargs.get("last_fingerprint")
        assert fp_a
        shutdown_scheduler()
        time.sleep(1)
        get_scheduler()
        job = get_scheduler().get_job(job_id)
        fp_after = job.kwargs.get("last_fingerprint")
        assert fp_after == fp_a
        r2 = run_task(goal="检查北方华创公开招聘，列出当前岗位名称。",
                      token_budget=150000, cost_budget=0.4,
                      project_id="bg-" + job_id + "-r2", model_mode="real",
                      max_model_calls=15, routing_intent="EXPLICIT",
                      routing_mode="BALANCED")
        s2 = _condition_check(job_id, r2, fp_after, "data")
        assert s2 in ("NO_CHANGE", "CONDITION_TRIGGERED")
        assert r2.run_id != r1.run_id
    finally:
        try:
            cancel_job(job_id, "data")
        except Exception:
            pass
        shutdown_scheduler()
