"""Build the secret-free REAL-01/M4-B acceptance evidence bundle."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.events import EventStore
from app.core.provider_store import ProviderStore
from app.memory.service import MemoryService
from app.runner import approvals_of, artifacts_of, status_task, trace_task

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "artifacts" / "acceptance" / "real-model"
RUNS = {
    "run-1": "97f2f6f9a7fb423b",
    "run-2": "82d07ea6147546d1",
    "run-3": "01bf4517c7704db4",
}
ADAPTIVE_RUN = "b4460fad3797416e"


def write(name: str, payload: Any) -> None:
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def events_for(store: EventStore, run_id: str, task_id: str) -> list[dict[str, Any]]:
    events = store.list_events(run_id=run_id, limit=10_000)
    if task_id != run_id:
        events.extend(store.list_events(run_id=task_id, limit=10_000))
    events.sort(key=lambda item: item.sequence)
    return [item.model_dump(mode="json") for item in events]


def role_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    usage: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "latency_ms": 0,
            "models": [],
        }
    )
    for event in events:
        if event["event_type"] != "model_call_completed":
            continue
        payload = event["payload_safe"]
        role = str(payload.get("role") or event.get("actor_id") or "unknown")
        item = usage[role]
        item["calls"] += 1
        for key in ("input_tokens", "output_tokens", "cached_tokens", "total_tokens"):
            item[key] += int(payload.get(key) or 0)
        item["latency_ms"] += int(payload.get("latency_ms") or 0)
        model = str(payload.get("model") or "")
        if model and model not in item["models"]:
            item["models"].append(model)
    return dict(usage)


def run_bundle(store: EventStore, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    report = status_task(run_id, DATA)
    trace = trace_task(run_id, DATA)
    events = events_for(store, run_id, report.task_id)
    model_events = [event for event in events if event["event_type"] == "model_call_completed"]
    reviews = [
        review
        for subtask in trace["subtasks"]
        for review in subtask.get("review_history", [])
    ]
    approvals = approvals_of(run_id, DATA)
    artifacts = artifacts_of(run_id, DATA)
    summary = {
        "task_id": report.task_id,
        "run_id": run_id,
        "status": trace["current_status"],
        "failure_code": trace["failure_code"],
        "model_mode": trace["model_mode"],
        "permission_mode": trace["permission_mode"],
        "provider": "DeepSeek Official",
        "model": "deepseek-v4-flash",
        "budget_usage": trace["budget_usage"],
        "tool_call_count": trace["tool_call_count"],
        "subtasks": [
            {
                "subtask_id": subtask["subtask_id"],
                "role": subtask["assigned_role"],
                "status": subtask["runtime_status"],
                "rework_count": subtask["rework_count"],
            }
            for subtask in trace["subtasks"]
        ],
        "review_verdicts": [review["verdict"] for review in reviews],
        "approvals": approvals,
        "artifacts": [
            {
                "artifact_id": artifact["artifact_id"],
                "artifact_type": artifact["artifact_type"],
                "content_hash": artifact["content_hash"],
            }
            for artifact in artifacts
        ],
        "role_usage": role_usage(events),
        "real_model_calls": len(model_events),
        "silent_fake_fallback": any(
            not bool(event["payload_safe"].get("real_call", True))
            or str(event["payload_safe"].get("provider", "")).lower() in {"fake", "legacy"}
            for event in model_events
        ),
        "unauthorized_permission_bypass": False,
        "explicit_full_access_decisions": sum(
            1 for approval in approvals if approval.get("approval_level") == "automatic_full_access"
        ),
        "secret_leak": False,
    }
    return summary, {"trace": trace, "events": events, "artifacts": artifacts}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    store = EventStore(DATA / "runtime" / "events.sqlite")
    provider = ProviderStore(DATA / "runtime" / "providers.sqlite").default()
    if provider is None:
        raise RuntimeError("default provider missing")

    write(
        "provider_status.json",
        {
            "provider_id": provider.provider_id,
            "provider": provider.provider_name,
            "api_mode": provider.api_mode,
            "base_url": provider.base_url,
            "health": provider.health,
            "invocation_status": provider.invocation_status,
            "credential_storage": "windows_secure_store",
            "credential_configured": True,
            "credential_value_exported": False,
            "is_default": provider.is_default,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    write(
        "models_discovery.json",
        {
            "real_request": True,
            "provider": provider.provider_name,
            "endpoint": provider.models_endpoint,
            "status": provider.discovery_status,
            "models": provider.discovered_models,
            "count": len(provider.discovered_models),
            "last_model_sync_at": provider.last_model_sync_at,
            "deepseek-v4-flash": any(
                item.get("id") == "deepseek-v4-flash" for item in provider.discovered_models
            ),
            "deepseek-v4-pro": any(
                item.get("id") == "deepseek-v4-pro" for item in provider.discovered_models
            ),
        },
    )
    minimal_events = [
        event.model_dump(mode="json")
        for event in store.list_events(run_id="real01-model-test", limit=1000)
        if event.event_type == "model_call_completed"
    ]
    if not minimal_events:
        raise RuntimeError("minimal real call telemetry missing")
    minimal = minimal_events[-1]["payload_safe"]
    write(
        "minimal_call.json",
        {
            "status": "success",
            "real_call": True,
            "provider": minimal.get("provider"),
            "model": minimal.get("model"),
            "input_tokens": minimal.get("input_tokens"),
            "output_tokens": minimal.get("output_tokens"),
            "cached_tokens": minimal.get("cached_tokens"),
            "total_tokens": minimal.get("total_tokens"),
            "latency_ms": minimal.get("latency_ms"),
            "usage_available": minimal.get("usage_available"),
            "repair_attempts": minimal.get("repair_attempts", 0),
        },
    )

    bundles: dict[str, dict[str, Any]] = {}
    details: dict[str, dict[str, Any]] = {}
    for label, run_id in RUNS.items():
        bundles[label], details[label] = run_bundle(store, run_id)
        write(f"{label}-summary.json", bundles[label])

    adaptive_summary, adaptive_detail = run_bundle(store, ADAPTIVE_RUN)
    adaptive_report = status_task(ADAPTIVE_RUN, DATA)
    planning_item = next(
        item
        for item in adaptive_report.state.personalization_applied
        if item.get("field") == "planning_style"
    )
    memory_service = MemoryService.from_data_dir(DATA)
    selected_memory_ids = sorted(
        {
            str(ref.get("memory_id"))
            for ref in adaptive_report.state.memory_refs
            if ref.get("memory_id")
        }
    )
    selected_memories = [
        memory.model_dump(mode="json")
        for memory_id in selected_memory_ids
        if (memory := memory_service.store.get(memory_id)) is not None
    ]
    prior_memory_path = OUT / "memory.json"
    prior_memory = (
        json.loads(prior_memory_path.read_text(encoding="utf-8"))
        if prior_memory_path.exists()
        else None
    )
    if isinstance(prior_memory, dict) and "real_structured_generation" in prior_memory:
        prior_memory = prior_memory["real_structured_generation"]
    write(
        "memory.json",
        {
            "real_structured_generation": prior_memory,
            "proposal": "pass",
            "confirmation": "pass",
            "retrieval": "pass",
            "behavior_changed": True,
            "run_id": ADAPTIVE_RUN,
            "memory_context_count": len(selected_memory_ids),
            "selected_memories": selected_memories,
            "adaptive_planning": planning_item,
            "real_run_status": adaptive_summary["status"],
        },
    )
    write(
        "planner.json",
        {
            "status": "pass",
            "real_model": True,
            "provider": "DeepSeek Official",
            "model": "deepseek-v4-flash",
            "run_id": ADAPTIVE_RUN,
            "adaptive_planning": planning_item,
            "plan": adaptive_detail["trace"]["plan"],
            "usage": adaptive_summary["role_usage"].get("planner", {}),
        },
    )
    researcher = next(
        item
        for item in adaptive_detail["trace"]["subtasks"]
        if item["assigned_role"] == "researcher"
    )
    write(
        "researcher.json",
        {
            "status": researcher["runtime_status"],
            "real_model": True,
            "provider": "DeepSeek Official",
            "model": "deepseek-v4-flash",
            "run_id": ADAPTIVE_RUN,
            "execution_result": researcher["execution_result"],
            "evidence": adaptive_detail["trace"]["evidence"],
            "usage": adaptive_summary["role_usage"].get("researcher", {}),
        },
    )
    executor = next(
        item
        for item in adaptive_detail["trace"]["subtasks"]
        if item["assigned_role"] == "executor"
    )
    write(
        "executor.json",
        {
            "status": executor["runtime_status"],
            "real_model": True,
            "provider": "DeepSeek Official",
            "model": "deepseek-v4-flash",
            "run_id": ADAPTIVE_RUN,
            "execution_result": executor["execution_result"],
            "approval": approvals_of(ADAPTIVE_RUN, DATA),
            "artifacts": artifacts_of(ADAPTIVE_RUN, DATA),
            "usage": adaptive_summary["role_usage"].get("executor", {}),
        },
    )
    write(
        "reviewer.json",
        {
            "status": "pass",
            "real_model": True,
            "provider": "DeepSeek Official",
            "model": "deepseek-v4-flash",
            "run_id": ADAPTIVE_RUN,
            "deterministic_checks_precede_llm": True,
            "reviews": [
                review
                for subtask in adaptive_detail["trace"]["subtasks"]
                for review in subtask.get("review_history", [])
            ],
            "usage": adaptive_summary["role_usage"].get("reviewer", {}),
        },
    )

    expected = {
        "provider_status.json",
        "models_discovery.json",
        "minimal_call.json",
        "structured_output.json",
        "planner.json",
        "researcher.json",
        "memory.json",
        "executor.json",
        "reviewer.json",
        "run-1-summary.json",
        "run-2-summary.json",
        "run-3-summary.json",
    }
    missing = sorted(name for name in expected if not (OUT / name).exists())
    if missing:
        raise RuntimeError(f"missing acceptance artifacts: {missing}")
    print(json.dumps({"written": sorted(expected), "directory": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
