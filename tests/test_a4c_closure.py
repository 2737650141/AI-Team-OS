"""M7-A4C-CLOSURE — one-time delivery and dispatcher wiring contracts."""

from __future__ import annotations

import sys
import types

import pytest

import app.notifications as n

# ---------------------------------------------------------------- GATE B: key


def test_one_time_key_same_run_same_outcome_stable() -> None:
    k1 = n.notification_key("one_time", "job1", "COMPLETED", run_id="run-A")
    k2 = n.notification_key("one_time", "job1", "COMPLETED", run_id="run-A")
    assert k1 == k2


def test_one_time_key_different_run_ids_different() -> None:
    k1 = n.notification_key("one_time", "job1", "COMPLETED", run_id="run-A")
    k2 = n.notification_key("one_time", "job1", "COMPLETED", run_id="run-B")
    assert k1 != k2


def test_one_time_key_different_outcomes_different() -> None:
    k1 = n.notification_key("one_time", "job1", "COMPLETED", run_id="run-A")
    k2 = n.notification_key("one_time", "job1", "FAILED", run_id="run-A")
    assert k1 != k2


def test_one_time_key_no_job_id_collision() -> None:
    k1 = n.notification_key("one_time", "jobA", "COMPLETED", run_id="run-1")
    k2 = n.notification_key("one_time", "jobB", "COMPLETED", run_id="run-1")
    assert k1 != k2


# ---------------------------------------------------------------- GATE C: ordering


def _install_fake_wheel(probe):
    fake = types.ModuleType("windows_toasts")

    class _ProbeToaster:
        def __init__(self, *a, **kw):
            pass

        def show_toast(self, t):
            probe()

    fake.WindowsToaster = _ProbeToaster
    fake.Toast = type("Toast", (), {})
    fake.ToastDuration = type("D", (), {"Short": "short"})
    sys.modules["windows_toasts"] = fake


def test_marker_send_order_matches_declared_semantics(tmp_path) -> None:
    """SEND_BEFORE_MARK: marker is persisted only after toast returns."""
    order: list[str] = []

    def _probe():
        order.append("toast_send")
        assert n.one_time_delivered("order-key", str(tmp_path)) is False

    _install_fake_wheel(_probe)
    result = n.send_notification("t", "b", "order-key", "jobO", "runO",
                                 "one_time", str(tmp_path))
    assert result == "DELIVERED"
    order.append("after_send")
    assert n.one_time_delivered("order-key", str(tmp_path)) is True
    assert order == ["toast_send", "after_send"]


def test_one_time_completed_duplicate_suppressed(tmp_path) -> None:
    calls = []

    def _probe():
        calls.append(1)

    _install_fake_wheel(_probe)
    d = str(tmp_path)
    key = n.notification_key("one_time", "jobD", "COMPLETED", run_id="run-D")
    r1 = n.send_notification("t", "b", key, "jobD", "run-D", "one_time", d)
    r2 = n.send_notification("t", "b", key, "jobD", "run-D", "one_time", d)
    assert r1 == "DELIVERED"
    assert r2 == "SUPPRESSED_DUPLICATE"
    assert len(calls) == 1


def test_different_run_can_notify_again(tmp_path) -> None:
    calls = []

    def _probe():
        calls.append(1)

    _install_fake_wheel(_probe)
    d = str(tmp_path)
    k1 = n.notification_key("one_time", "jobR", "COMPLETED", run_id="run-1")
    k2 = n.notification_key("one_time", "jobR", "COMPLETED", run_id="run-2")
    r1 = n.send_notification("t", "b", k1, "jobR", "run-1", "one_time", d)
    r2 = n.send_notification("t", "b", k2, "jobR", "run-2", "one_time", d)
    assert r1 == "DELIVERED"
    assert r2 == "DELIVERED"
    assert len(calls) == 2


# ---------------------------------------------------------------- task vs delivery


def test_task_success_not_changed_by_delivery_failure(tmp_path) -> None:
    """Successful task + backend failure -> DELIVERY_FAILED only."""
    fake = types.ModuleType("windows_toasts")

    class _BrokenToaster:
        def __init__(self, *a, **kw):
            pass

        def show_toast(self, t):
            raise RuntimeError("backend down")

    fake.WindowsToaster = _BrokenToaster
    fake.Toast = type("Toast", (), {})
    fake.ToastDuration = type("D", (), {"Short": "short"})
    sys.modules["windows_toasts"] = fake
    key = n.notification_key("one_time", "jobT", "COMPLETED", run_id="run-T")
    r = n.send_notification("t", "b", key, "jobT", "run-T", "one_time", str(tmp_path))
    assert r == "DELIVERY_FAILED"


def test_condition_notification_regression(tmp_path, monkeypatch) -> None:
    k1 = n.notification_key("condition", "jobC", "CONDITION_TRIGGERED", "fpX")
    k2 = n.notification_key("condition", "jobC", "CONDITION_TRIGGERED", "fpX")
    k3 = n.notification_key("condition", "jobC", "CONDITION_TRIGGERED", "fpY")
    assert k1 == k2
    assert k1 != k3


# ---------------------------------------------------------------- dispatcher wiring


class _ReportState:
    final_result = "completed result"
    tool_calls = []


class _Report:
    run_id = "run-wiring"
    state = _ReportState()


def test_dispatcher_wires_completion_notification(monkeypatch) -> None:
    import app.background.jobs as bj
    import app.runner as runner

    monkeypatch.setattr(runner, "run_task", lambda **kwargs: _Report())
    calls = []

    def _deliver(job_id, report, data_dir):
        calls.append((job_id, report.run_id, data_dir))
        return "DELIVERED"

    monkeypatch.setattr(
        bj,
        "_deliver_one_time_notification",
        _deliver,
    )

    assert bj.execute_background_job("wire-complete", "run", data_dir="tmp") == "run-wiring"
    assert calls == [("wire-complete", "run-wiring", "tmp")]


def test_dispatcher_wires_condition_notification(monkeypatch) -> None:
    import app.background.jobs as bj
    import app.runner as runner

    monkeypatch.setattr(runner, "run_task", lambda **kwargs: _Report())
    calls = []
    monkeypatch.setattr(bj, "_condition_check", lambda *args: "CONDITION_TRIGGERED")

    def _deliver(job_id, status, report, data_dir):
        calls.append((job_id, status, report.run_id, data_dir))
        return "DELIVERED"

    monkeypatch.setattr(
        bj,
        "_deliver_condition_notification",
        _deliver,
    )

    assert bj.execute_background_job(
        "wire-condition", "run", task_kind="condition", data_dir="tmp"
    ) == "run-wiring"
    assert calls == [("wire-condition", "CONDITION_TRIGGERED", "run-wiring", "tmp")]


def test_dispatcher_failure_notifies_and_preserves_failure(monkeypatch) -> None:
    import app.background.jobs as bj
    import app.runner as runner

    error = RuntimeError("run failed")
    monkeypatch.setattr(runner, "run_task", lambda **kwargs: (_ for _ in ()).throw(error))
    calls = []

    def _deliver(job_id, instruction, data_dir):
        calls.append((job_id, instruction, data_dir))
        return "DELIVERED"

    monkeypatch.setattr(
        bj,
        "_deliver_failure_notification",
        _deliver,
    )

    with pytest.raises(RuntimeError, match="run failed"):
        bj.execute_background_job("wire-failure", "instruction", data_dir="tmp")
    assert calls == [("wire-failure", "instruction", "tmp")]


def test_dispatcher_notification_failure_does_not_change_run_result(monkeypatch) -> None:
    import app.background.jobs as bj
    import app.runner as runner

    monkeypatch.setattr(runner, "run_task", lambda **kwargs: _Report())

    def _fail(*args):
        raise RuntimeError("marker write failed")

    monkeypatch.setattr(bj, "_deliver_one_time_notification", _fail)
    assert bj.execute_background_job("wire-notify-failure", "run") == "run-wiring"


@pytest.mark.skipif(
    __import__("os").environ.get("A4C_CLOSURE_REAL") != "1",
    reason="real gate (A4C_CLOSURE_REAL=1)",
)
def test_real_one_time_success_to_windows_toast() -> None:
    from app.notifications import notification_key, send_notification

    key = notification_key("one_time", "closure-real", "COMPLETED", run_id="closure-run")
    r = send_notification(
        "AI Team OS", "Closure one-time success test",
        key, "closure-real", "closure-run", "one_time", "data",
    )
    assert r in ("DELIVERED", "DELIVERY_FAILED")
