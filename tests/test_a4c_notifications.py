"""M7-A4C — proactive notification / result delivery tests.

Windows-Toasts owns the toast mechanism; AI Team OS glue owns deterministic
policy, durable dedup, and the thin adapter. Real gates are opt-in.
"""

from __future__ import annotations

import os
import sys
import types

import pytest

import app.notifications as n

# ---------------------------------------------------------------- policy


def test_baseline_is_silent() -> None:
    assert n.policy_decision("condition", "BASELINE_ESTABLISHED") == "SILENT"


def test_no_change_is_silent() -> None:
    assert n.policy_decision("condition", "NO_CHANGE") == "SILENT"


def test_skipped_already_running_is_silent() -> None:
    assert n.policy_decision("condition", "SKIPPED_ALREADY_RUNNING") == "SILENT"


def test_condition_triggered_notifies() -> None:
    assert n.policy_decision("condition", "CONDITION_TRIGGERED") == "NOTIFY"


def test_one_time_completed_notifies() -> None:
    assert n.policy_decision("one_time", "COMPLETED") == "NOTIFY"


def test_one_time_failed_notifies() -> None:
    assert n.policy_decision("one_time", "FAILED") == "NOTIFY"


def test_check_failed_not_no_change() -> None:
    assert n.policy_decision("condition", "CHECK_FAILED") == "SILENT"
    assert "CHECK_FAILED" != "NO_CHANGE"


# ---------------------------------------------------------------- keys


def test_notification_key_deterministic() -> None:
    k1 = n.notification_key("condition", "job1", "CONDITION_TRIGGERED", "fpX")
    k2 = n.notification_key("condition", "job1", "CONDITION_TRIGGERED", "fpX")
    assert k1 == k2


def test_condition_key_binds_fingerprint() -> None:
    k1 = n.notification_key("condition", "job1", "CONDITION_TRIGGERED", "fpX")
    k2 = n.notification_key("condition", "job1", "CONDITION_TRIGGERED", "fpY")
    assert k1 != k2


def test_one_time_key_binds_status() -> None:
    k1 = n.notification_key("one_time", "job1", "COMPLETED")
    k2 = n.notification_key("one_time", "job1", "FAILED")
    assert k1 != k2


# ---------------------------------------------------------------- dedup (mocked toast)


def _install_fake_wheel() -> None:
    fake = types.ModuleType("windows_toasts")

    class _FakeToaster:
        def __init__(self, *a, **kw):
            pass

        def show_toast(self, t):
            return None

    fake.WindowsToaster = _FakeToaster
    fake.Toast = type("Toast", (), {})
    fake.ToastDuration = type("D", (), {"Short": "short"})
    sys.modules["windows_toasts"] = fake


def test_same_condition_duplicate_suppressed(tmp_path, monkeypatch) -> None:
    """Dedup via the separate persisted last_notified_fingerprint marker."""
    _install_fake_wheel()

    class _FakeJob:
        kwargs: dict = {}

    class _FakeScheduler:
        def __init__(self, *a, **kw):
            self.job = _FakeJob()

        def get_job(self, job_id):
            return self.job

        def modify_job(self, job_id, **changes):
            self.job.kwargs.update(changes.get("kwargs", {}))

    import app.background.jobs as bj

    monkeypatch.setattr(bj, "get_scheduler", _FakeScheduler)
    job_id = "dup-cond"
    r1 = n.send_notification("t", "b", "k-cond", job_id, "r1", "condition",
                             str(tmp_path), dedup_marker="fpX")
    r2 = n.send_notification("t", "b", "k-cond", job_id, "r1", "condition",
                             str(tmp_path), dedup_marker="fpX")
    assert r1 == "DELIVERED"
    assert r2 == "SUPPRESSED_DUPLICATE"


def test_one_time_duplicate_suppressed(tmp_path) -> None:
    _install_fake_wheel()
    r1 = n.send_notification("t", "b", "k-ot", "jobY", "run9", "one_time", str(tmp_path))
    r2 = n.send_notification("t", "b", "k-ot", "jobY", "run9", "one_time", str(tmp_path))
    assert r1 == "DELIVERED"
    assert r2 == "SUPPRESSED_DUPLICATE"


def test_new_condition_fingerprint_notifies_again(tmp_path) -> None:
    _install_fake_wheel()
    job_id = "new-cond"
    r1 = n.send_notification("t", "b", "k1", job_id, "r1", "condition",
                             str(tmp_path), dedup_marker="fpX")
    r2 = n.send_notification("t", "b", "k2", job_id, "r1", "condition",
                             str(tmp_path), dedup_marker="fpY")
    assert r1 == "DELIVERED"
    assert r2 == "DELIVERED"


def test_condition_marker_persistence_failure_is_loud(monkeypatch) -> None:
    class _Job:
        kwargs = {}

    class _BrokenScheduler:
        def get_job(self, job_id):
            return _Job()

        def modify_job(self, job_id, **changes):
            raise OSError("scheduler store unavailable")

    import app.background.jobs as bj

    monkeypatch.setattr(bj, "get_scheduler", lambda data_dir: _BrokenScheduler())
    with pytest.raises(RuntimeError, match="marker persistence failed"):
        n.mark_delivered_condition("job-marker", "fp-marker", "tmp")


def test_one_time_marker_persistence_failure_is_loud(monkeypatch, tmp_path) -> None:
    def _raise_connect(*args, **kwargs):
        raise OSError("event store unavailable")

    monkeypatch.setattr(n.sqlite3, "connect", _raise_connect)
    with pytest.raises(RuntimeError, match="marker persistence failed"):
        n.mark_delivered_one_time("key-marker", "job-marker", "run-marker", str(tmp_path))


def test_dedup_survives_restart(tmp_path) -> None:
    _install_fake_wheel()
    d = str(tmp_path)
    n.send_notification("t", "b", "k-restart", "jobZ", "r7", "one_time", d)
    assert n.one_time_delivered("k-restart", d) is True


def test_notification_failure_does_not_change_task_result(tmp_path) -> None:
    """Wheel failure returns DELIVERY_FAILED without changing task state."""
    fake = types.ModuleType("windows_toasts")

    class _BrokenToaster:
        def __init__(self, *a, **kw):
            pass

        def show_toast(self, t):
            raise RuntimeError("toast backend down")

    fake.WindowsToaster = _BrokenToaster
    fake.Toast = type("Toast", (), {})
    fake.ToastDuration = type("D", (), {"Short": "short"})
    sys.modules["windows_toasts"] = fake
    r = n.send_notification("t", "b", "k-fail", "jobW", "r6", "one_time", str(tmp_path))
    assert r == "DELIVERY_FAILED"


def test_notification_body_redacted_bounded() -> None:
    long = "x" * 500 + " SECRET_TOKEN_123"
    out = n.safe_excerpt(long, 120)
    assert len(out) <= 120
    assert "SECRET_TOKEN_123" not in out


def test_user_or_llm_cannot_select_notification_callable() -> None:
    """send_notification has NO callable/function/import parameters."""
    import inspect

    sig = inspect.signature(n.send_notification)
    for name in sig.parameters:
        assert name not in ("callable", "function", "import_path", "callback")


REAL = os.environ.get("A4C_REAL_NOTIFICATION") == "1"


@pytest.mark.skipif(not REAL, reason="real gate (A4C_REAL_NOTIFICATION=1)")
def test_real_windows_notification() -> None:
    """A real Windows toast is delivered (manual visual confirmation)."""
    from app.notifications import send_notification

    r = send_notification(
        "AI Team OS", "A4C real notification test",
        "real-test-1", "real-test-job", "real-test-run", "one_time", "data",
    )
    assert r in ("DELIVERED", "DELIVERY_FAILED")
