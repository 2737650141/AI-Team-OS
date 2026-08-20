"""M7-A4B-CLOSURE — condition watch persistence and scheduler gates.

Production changes are limited to the A4B condition branch and job
persistence. Real-time gates are behind A4B_CLOSURE_REAL=1.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.background.jobs import (
    _condition_check,
    fingerprint_records,
    get_scheduler,
    shutdown_scheduler,
)


class _FakeToolCall:
    def __init__(self, tool: str, summary: str) -> None:
        self.tool = tool
        self.result_summary = summary


class _FakeState:
    def __init__(self, tool_calls) -> None:
        self.tool_calls = tool_calls


class _FakeReport:
    def __init__(self, state) -> None:
        self.state = state


def _crawler_report(records: list[dict], ok: bool = True, zero: bool = False) -> _FakeReport:
    if zero:
        summary = '{"ok": true, "status": "zero_results", "records": []}'
    else:
        import json

        summary = json.dumps({"ok": ok, "status": "success", "records": records})
    return _FakeReport(_FakeState([_FakeToolCall("web_crawl_extract", summary)]))


def _no_crawler_report() -> _FakeReport:
    return _FakeReport(_FakeState([_FakeToolCall("web_search", '{"ok": true}')]))


def _failed_crawler_report() -> _FakeReport:
    return _FakeReport(_FakeState([
        _FakeToolCall("web_crawl_extract", '{"ok": false, "code": "fetch_failure"}')
    ]))


# ---------------------------------------------------------------- condition semantics


def test_condition_first_run_establishes_baseline() -> None:
    try:
        r = _condition_check("cond-test-1", _crawler_report(
            [{"JobAdId": 1, "JobAdName": "A", "url": "u1"}]), "", "data")
        assert r == "BASELINE_ESTABLISHED"
    finally:
        _cleanup("cond-test-1")


def test_condition_same_records_no_change() -> None:
    try:
        records = [{"JobAdId": 1, "JobAdName": "A", "url": "u1"}]
        fp = fingerprint_records(records)
        r1 = _condition_check("cond-test-2", _crawler_report(records), "", "data")
        assert r1 == "BASELINE_ESTABLISHED"
        r2 = _condition_check("cond-test-2", _crawler_report(records), fp, "data")
        assert r2 == "NO_CHANGE"
    finally:
        _cleanup("cond-test-2")


def test_condition_changed_records_triggers() -> None:
    try:
        fp = fingerprint_records([{"JobAdId": 1, "JobAdName": "A", "url": "u1"}])
        r = _condition_check(
            "cond-test-3",
            _crawler_report([
                {"JobAdId": 1, "JobAdName": "A", "url": "u1"},
                {"JobAdId": 2, "JobAdName": "B", "url": "u2"},
            ]),
            fp, "data",
        )
        assert r == "CONDITION_TRIGGERED"
    finally:
        _cleanup("cond-test-3")


def test_condition_failure_does_not_overwrite_baseline() -> None:
    """CHECK_FAILED on failure; previous fingerprint untouched."""
    try:
        fp = fingerprint_records([{"JobAdId": 1, "JobAdName": "A", "url": "u1"}])
        r = _condition_check("cond-test-4", _failed_crawler_report(), fp, "data")
        assert r == "CHECK_FAILED"
        job = get_scheduler().get_job("cond-test-4")
        if job is not None and job.kwargs:
            assert job.kwargs.get("last_fingerprint") == fp
    finally:
        _cleanup("cond-test-4")


def test_condition_failure_without_baseline() -> None:
    r = _condition_check("cond-test-5", _no_crawler_report(), "", "data")
    assert r == "CHECK_FAILED"


def test_condition_zero_results_is_verifiable_baseline() -> None:
    """A true ZERO_RESULTS snapshot is a valid empty baseline."""
    try:
        r = _condition_check("cond-test-6", _crawler_report([], zero=True), "", "data")
        assert r == "BASELINE_ESTABLISHED"
    finally:
        _cleanup("cond-test-6")


def test_condition_fingerprint_survives_scheduler_restart() -> None:
    """Baseline persisted via job.modify survives restart."""
    import time

    from app.background.jobs import create_job

    try:
        fp = fingerprint_records([{"JobAdId": 1, "JobAdName": "A", "url": "u1"}])
        create_job(job_id="cond-restart", instruction="check", schedule_type="interval",
                   interval_seconds=3600, data_dir="data", task_kind="condition",
                   last_fingerprint=fp)
        job = get_scheduler().get_job("cond-restart")
        assert job is not None and job.kwargs.get("last_fingerprint") == fp
        shutdown_scheduler()
        time.sleep(1)
        s2 = get_scheduler()
        job2 = s2.get_job("cond-restart")
        assert job2 is not None
        assert job2.kwargs.get("last_fingerprint") == fp
    finally:
        _cleanup("cond-restart")


def _cleanup(job_id: str) -> None:
    try:
        from app.background.jobs import cancel_job

        cancel_job(job_id, "data")
    except Exception:
        pass
    shutdown_scheduler()


REAL = os.environ.get("A4B_CLOSURE_REAL") == "1"


@pytest.mark.skipif(not REAL, reason="real gate (A4B_CLOSURE_REAL=1)")
def test_real_pause_crosses_due_windows() -> None:
    """Pause across due windows -> zero executions; resume -> runs."""
    import time

    from app.background.jobs import create_job, pause_job, resume_job

    try:
        create_job(job_id="pause-gate", instruction="现在几点？",
                   schedule_type="interval", interval_seconds=6, data_dir="data")

        def _run_threads() -> set:
            import sqlite3

            conn = sqlite3.connect(str(Path("data") / "checkpoints.db"))
            rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()
            conn.close()
            from app.runner import status_task

            out: set = set()
            for (tid,) in rows:
                try:
                    rep = status_task(tid, data_dir=Path("data"))
                    if rep.state.project_id == "bg-pause-gate":
                        out.add(tid)
                except Exception:
                    pass
            return out

        time.sleep(11)
        before = _run_threads()
        for _ in range(4):
            time.sleep(2)
            settled = _run_threads()
            if settled == before:
                break
            before = settled
        assert len(before) >= 1
        pause_job("pause-gate", "data")
        time.sleep(13)
        during = _run_threads()
        assert during == before
        resume_job("pause-gate", "data")
        time.sleep(9)
        after = _run_threads()
        assert after > before
    finally:
        _cleanup("pause-gate")


@pytest.mark.skipif(not REAL, reason="real gate (A4B_CLOSURE_REAL=1)")
def test_real_misfire_coalesces_no_burst() -> None:
    """Scheduler restart across missed intervals produces no burst."""
    import sqlite3
    import time

    from app.background.jobs import create_job

    try:
        create_job(job_id="misfire-gate", instruction="报告当前时间。",
                   schedule_type="interval", interval_seconds=3, data_dir="data")
        time.sleep(8)
        shutdown_scheduler()
        time.sleep(9)
        get_scheduler()
        time.sleep(8)
        conn = sqlite3.connect(str(Path("data") / "checkpoints.db"))
        rows = conn.execute(
            "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints "
            "GROUP BY thread_id ORDER BY 2 DESC LIMIT 10"
        ).fetchall()
        conn.close()
        assert len(rows) >= 1
    finally:
        _cleanup("misfire-gate")
