"""Run the REL-01 five-task real-model reliability seal."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.core.events import EventStore
from app.core.schemas import ApprovalPayload
from app.runner import approvals_of, resume_task, run_task, status_task, trace_task

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "artifacts" / "acceptance" / "rel01"

GOALS = [
    (
        "sandbox_REAL01：检查示例 Python 项目的失败测试，定位根因，提出最小修复；"
        "经标准审批后修改并运行 pytest，由 Reviewer 审核。REL01-1"
    ),
    (
        "sandbox_REAL01：只读分析 is_even 测试与实现的矛盾，再由 Executor 做最小代码"
        "修复、标准审批、pytest 验证和 Reviewer 审核。REL01-2"
    ),
    (
        "sandbox_REAL01：找出示例项目奇偶判断的失败原因，不修改测试；"
        "执行最小补丁并通过 pytest 和 Reviewer。REL01-3"
    ),
    "sandbox_REAL01：诊断当前唯一失败测试，保持公开接口不变，最小修复实现并完成标准审批、测试和独立审查。REL01-4",
    (
        "sandbox_REAL01：修复示例 Python 项目的反向奇偶逻辑；Researcher 只做取证，"
        "Executor 负责补丁和 pytest，Reviewer 最终验收。REL01-5"
    ),
]


def event_bundle(run_id: str, task_id: str) -> list[dict[str, Any]]:
    store = EventStore(DATA / "runtime" / "events.sqlite")
    events = store.list_events(run_id=run_id, limit=10_000)
    if task_id != run_id:
        events.extend(store.list_events(run_id=task_id, limit=10_000))
    unique = {item.sequence: item for item in events}
    return [unique[key].model_dump(mode="json") for key in sorted(unique)]


def summarize(run_id: str) -> dict[str, Any]:
    report = status_task(run_id, DATA)
    trace = trace_task(run_id, DATA)
    events = event_bundle(run_id, report.task_id)
    model_events = [item for item in events if item["event_type"] == "model_call_completed"]
    approvals = approvals_of(run_id, DATA)
    security_codes = {
        "role_forbidden",
        "tool_forbidden",
        "path_outside_allowlist",
        "ssrf_blocked",
        "secret_detected",
    }
    return {
        "task_id": report.task_id,
        "run_id": run_id,
        "status": trace["current_status"],
        "failure_code": trace["failure_code"],
        "provider": "DeepSeek Official",
        "model": "deepseek-v4-flash",
        "model_mode": trace["model_mode"],
        "permission_mode": trace["permission_mode"],
        "budget_usage": trace["budget_usage"],
        "subtasks": [
            {
                "subtask_id": item["subtask_id"],
                "role": item["assigned_role"],
                "status": item["runtime_status"],
                "rework_count": item["rework_count"],
                "review_verdicts": [review["verdict"] for review in item["review_history"]],
            }
            for item in trace["subtasks"]
        ],
        "real_model_calls": len(model_events),
        "fake_fallback": any(
            not bool(item["payload_safe"].get("real_call", True))
            or str(item["payload_safe"].get("provider", "")).lower() in {"fake", "legacy"}
            for item in model_events
        ),
        "security_violation": any(
            str(item["payload_safe"].get("error_code", "")) in security_codes for item in events
        ),
        "approval_bypass": any(item["event_type"] == "approval_bypassed" for item in events),
        "infinite_rework": any(item["rework_count"] > 3 for item in trace["subtasks"]),
        "approvals": [
            {
                "approval_id": item["approval_id"],
                "status": item["status"],
                "approval_level": item["approval_level"],
            }
            for item in approvals
        ],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["AI_TEAM_ALLOWED_READ_ROOTS"] = str(ROOT / "fixtures")
    runs: list[dict[str, Any]] = []
    for index, goal in enumerate(GOALS, 1):
        report = run_task(
            goal,
            token_budget=50000,
            cost_budget=2.0,
            project_id=f"rel01-{index}",
            data_dir=DATA,
            model_mode="real",
            model_overrides={"project_alias": "real01_python"},
            max_model_calls=30,
            permission_mode="standard",
        )
        approval_rounds = 0
        while report.state.current_status == "paused" and approval_rounds < 3:
            approval_id = report.state.pending_approval_id
            if not approval_id:
                break
            report = resume_task(
                report.run_id or "",
                payload=ApprovalPayload(
                    approval_id=approval_id,
                    decision="approved",
                    reason="REL-01 bounded acceptance approval",
                ),
                data_dir=DATA,
                model_mode="real",
                model_overrides={"project_alias": "real01_python"},
            )
            approval_rounds += 1
        summary = summarize(report.run_id or "")
        summary["acceptance_index"] = index
        summary["approval_rounds"] = approval_rounds
        (OUT / f"run-{index}-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        runs.append(summary)
        print(
            json.dumps(
                {
                    "index": index,
                    "run_id": summary["run_id"],
                    "status": summary["status"],
                    "failure_code": summary["failure_code"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    passed = sum(item["status"] == "completed" for item in runs)
    result = {
        "artifact": "REAL_RUNTIME_RELIABILITY",
        "baseline": {"pass": 2, "total": 3, "pass_rate": 2 / 3},
        "new_runs": len(runs),
        "pass": passed,
        "fail": len(runs) - passed,
        "pass_rate": passed / len(runs),
        "fake_fallback": sum(bool(item["fake_fallback"]) for item in runs),
        "security_violation": sum(bool(item["security_violation"]) for item in runs),
        "approval_bypass": sum(bool(item["approval_bypass"]) for item in runs),
        "infinite_rework": sum(bool(item["infinite_rework"]) for item in runs),
        "runs": [item["run_id"] for item in runs],
        "failures_retained": [item["run_id"] for item in runs if item["status"] != "completed"],
    }
    (OUT / "REAL_RUNTIME_RELIABILITY.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return (
        0
        if passed >= 4
        and all(
            result[key] == 0
            for key in (
                "fake_fallback",
                "security_violation",
                "approval_bypass",
                "infinite_rework",
            )
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
