from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.gateway.contracts import ModelRequest, ModelResponse, UsageEstimate
from app.usage.context import ContextCompactor, ContextPolicy
from app.usage.models import CostSource, NormalizedModelUsage, UsageSource, verified_model_profile
from app.usage.reconciler import UsageReconciler
from app.usage.store import UsageStore


def request(call: str = "call-1", role: str = "executor", agent: str = "executor"):
    return ModelRequest(
        request_id=call,
        task_id="task-1",
        run_id="run-1",
        agent_id=agent,
        role_type=role,
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "not persisted"}],
    )


def normalized(call: str = "call-1", **updates) -> NormalizedModelUsage:
    values = dict(
        usage_id=f"usage-{call}",
        task_id="task-1",
        run_id="run-1",
        call_id=call,
        role="executor",
        agent_id="executor",
        provider_id="deepseek",
        provider_name="DeepSeek Official",
        model_id="deepseek-v4-flash",
        input_tokens=100,
        output_tokens=20,
        reasoning_tokens=None,
        cached_input_tokens=None,
        total_tokens=120,
        usage_source=UsageSource.REPORTED,
        latency_ms=25,
        cost_source=CostSource.UNAVAILABLE,
    )
    values.update(updates)
    return NormalizedModelUsage(**values)


def test_gt_tok01_provider_usage_normalization():
    usage = UsageReconciler.deepseek_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 30,
            "total_tokens": 130,
            "prompt_cache_hit_tokens": 40,
            "completion_tokens_details": {"reasoning_tokens": 12},
        }
    )
    assert usage == {
        "input_tokens": 100,
        "output_tokens": 30,
        "reasoning_tokens": 12,
        "cached_input_tokens": 40,
        "cache_write_tokens": None,
        "other_tokens": None,
        "total_tokens": 130,
    }


def test_gt_tok02_no_data_state(tmp_path):
    result = UsageStore(tmp_path).summary()
    assert result["has_data"] is False and result["total_tokens"] is None


def test_gt_tok03_prompt_output_count():
    item = UsageReconciler.response(
        request(),
        ModelResponse(
            request_id="call-1",
            provider="deepseek",
            model="m",
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
            usage_source="REPORTED",
        ),
        UsageEstimate(estimated_input_tokens=10, estimated_max_output_tokens=8),
        cost_total=None,
    )
    assert (item.input_tokens, item.output_tokens, item.total_tokens) == (11, 7, 18)


def test_gt_tok04_reasoning_unavailable():
    assert normalized().reasoning_tokens is None


def test_gt_tok05_cache_unavailable():
    assert normalized().cached_input_tokens is None


def test_gt_tok06_context_known():
    assert ContextPolicy().status(70, 100).value == "MODERATE"


def test_gt_tok07_context_unknown():
    assert ContextPolicy().status(70, None).value == "UNKNOWN"


def test_verified_deepseek_v4_flash_context_profile():
    profile = verified_model_profile("DeepSeek Official", "deepseek-v4-flash")
    assert profile is not None
    assert profile.context_window == 1_000_000
    assert profile.max_output_tokens == 384_000


def test_gt_tok08_80_percent_compaction_threshold():
    assert ContextPolicy().status(80, 100).value == "NEAR_COMPACTION"


def test_gt_tok09_compaction_before_after_preserves_critical_fields():
    checkpoint, metrics = ContextCompactor().compact(
        task_id="task-1",
        run_id="run-1",
        role="reviewer",
        model="m",
        current_tokens=900,
        context_limit=1000,
        critical={
            "user_goal": "ship",
            "constraints": ["safe"],
            "important_ids": ["A-1"],
            "files_being_edited": ["app.py"],
            "test_failures": ["test_x"],
            "reviewer_requirements": ["fix x"],
            "approval_state": "not_required",
        },
    )
    assert metrics["before"] == 900 and metrics["after"] < 900
    assert checkpoint.user_goal == "ship" and checkpoint.important_ids == ["A-1"]


def test_gt_tok10_11_17_18_19_group_totals(tmp_path):
    store = UsageStore(tmp_path)
    store.record(normalized("a", role="planner", agent_id="planner"))
    store.record(normalized("b", provider_name="OpenAI", model_id="gpt", total_tokens=50))
    result = store.summary(run_id="run-1", days=None)
    assert result["total_tokens"] == 170 and result["requests"] == 2
    assert len(result["by_agent"]) == len(result["by_model"]) == len(result["by_provider"]) == 2


def test_gt_tok12_no_double_count_cached_tokens():
    usage = UsageReconciler.openai_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 80},
        }
    )
    assert usage["total_tokens"] == 120


def test_gt_tok13_cost_unavailable(tmp_path):
    store = UsageStore(tmp_path)
    store.record(normalized())
    assert store.summary(days=None)["cost_total"] is None


def test_gt_tok14_retention(tmp_path):
    store = UsageStore(tmp_path)
    store.record(normalized())
    with sqlite3.connect(store.path) as conn:
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        conn.execute("UPDATE model_usage SET timestamp=?", (old,))
    assert store.prune() == 1 and store.summary(days=None)["has_data"] is False


def test_gt_tok15_secret_free_telemetry(tmp_path):
    store = UsageStore(tmp_path)
    store.record(normalized())
    schema = sqlite3.connect(store.path).execute("PRAGMA table_info(model_usage)").fetchall()
    names = {row[1] for row in schema}
    assert not names & {"prompt", "messages", "response", "secret", "api_key", "chain_of_thought"}


def test_gt_tok16_restart_persistence(tmp_path):
    UsageStore(tmp_path).record(normalized())
    assert UsageStore(tmp_path).summary(days=None)["requests"] == 1


def test_gt_tok20_real_deepseek_usage_contract():
    # Live acceptance is deliberately separate and credential-gated. This verifies that a
    # final provider response replaces the pre-call estimate and remains explicitly REPORTED.
    item = UsageReconciler.response(
        request(),
        ModelResponse(
            request_id="call-1",
            provider="deepseek",
            model="deepseek-v4-flash",
            input_tokens=9,
            output_tokens=2,
            total_tokens=11,
            latency_ms=12,
            usage_source="REPORTED",
            usage_available=True,
        ),
        UsageEstimate(estimated_input_tokens=100, estimated_max_output_tokens=100),
        cost_total=None,
    )
    assert item.usage_source is UsageSource.REPORTED and item.total_tokens == 11
    assert item.estimated_input_tokens == 100 and item.latency_ms > 0


def test_desktop_sidecar_is_loopback_only():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "app"
        / "desktop_sidecar.py"
    ).read_text(encoding="utf-8")
    assert '"127.0.0.1"' in source
    assert 'host="127.0.0.1"' in source
    assert 'host="0.0.0.0"' not in source


def test_desktop_session_token_is_not_passed_on_command_line():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    rust = (root / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert '.env("AI_TEAM_OS_DESKTOP_SESSION_TOKEN", &token)' in rust
    assert '"--session-token".to_string()' not in rust


def test_desktop_private_network_preflight(monkeypatch):
    """WebView2 receives explicit PNA permission for authenticated localhost writes."""
    from fastapi.testclient import TestClient

    from app.api.server import app

    monkeypatch.setenv("AI_TEAM_OS_DESKTOP_SESSION_TOKEN", "desktop-test-token")
    response = TestClient(app).options(
        "/tasks",
        headers={
            "Origin": "https://tauri.localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-desktop-session",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert response.status_code == 204
    assert response.headers["access-control-allow-private-network"] == "true"


def test_desktop_window_has_explicit_ipc_capability():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    capability = json.loads(
        (root / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8")
    )
    assert config["app"]["security"]["capabilities"] == [capability["identifier"]]
    assert capability["windows"] == ["main"]
    assert "core:default" in capability["permissions"]


def test_desktop_bundle_includes_runtime_fixtures():
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "build_desktop_release.ps1"
    ).read_text(encoding="utf-8")
    assert '--add-data "app\\tools\\fixtures;app\\tools\\fixtures"' in script


def test_desktop_sidecar_watches_shell_parent():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sidecar = (root / "app" / "desktop_sidecar.py").read_text(encoding="utf-8")
    rust = (root / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert 'parser.add_argument("--parent-pid"' in sidecar
    assert "WaitForSingleObject" in sidecar
    assert '"--parent-pid".to_string()' in rust
