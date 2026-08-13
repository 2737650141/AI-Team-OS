"""Audit the ten real STANDARD plans already executed by PRODUCT-02."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.orchestration import RoleRouter
from app.runner import trace_task

ROOT = Path(__file__).resolve().parents[2]
EXPANDED = ROOT / "docs" / "acceptance" / "PRODUCT02_EXPANDED_BENCHMARK.md"
REPORT = ROOT / "docs" / "acceptance" / "PRODUCT02_PLANNER_CALIBRATION.md"


def main() -> int:
    text = EXPANDED.read_text(encoding="utf-8")
    payload = json.loads(text.split("```json", 1)[1].split("```", 1)[0])
    source = payload["suites"].get("standard", [])
    rows = []
    for sample in source:
        trace = trace_task(sample["run_id"], ROOT / "data")
        subtasks = [item for item in trace["subtasks"] if not item.get("superseded")]
        role_ok = all(
            RoleRouter().validate(
                item.get("capability_required") or "research", item["assigned_role"]
            )
            for item in subtasks
        )
        budget_ok = sum(int(item["token_budget"]) for item in subtasks) <= 60000
        bounded = len(subtasks) <= 4
        executable = all(item["assigned_role"] in {"researcher", "executor"} for item in subtasks)
        shape = trace.get("task_shape")
        unnecessary = any(item["assigned_role"] == "executor" for item in subtasks) and shape in {
            "read_only_research",
            "code_analysis",
        }
        rows.append(
            {
                "id": sample["id"],
                "run_id": sample["run_id"],
                "subtasks": len(subtasks),
                "bounded": bounded,
                "role_capability": role_ok,
                "budget": budget_ok,
                "executable": executable,
                "no_unnecessary_agents": not unnecessary,
                "passed": all((bounded, role_ok, budget_ok, executable, not unnecessary)),
            }
        )
    gate = len(rows) == 10 and all(row["passed"] for row in rows)
    out = {
        "phase": "PRODUCT-02",
        "source": "real_standard_trace",
        "total": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "standard_max_subtasks": max((row["subtasks"] for row in rows), default=0),
        "gate": gate,
        "rows": rows,
    }
    lines = [
        "# PRODUCT-02 Planner Calibration",
        "",
        "- Source: 10 real STANDARD task traces",
        f"- Gate: {'PASS' if gate else 'FAIL'}",
        f"- Max subtasks observed: {out['standard_max_subtasks']} (limit 4)",
        "- Executable role/capability correctness: "
        + ("100%" if all(r["role_capability"] and r["executable"] for r in rows) else "FAIL"),
        "- Budget compliance: " + ("100%" if all(r["budget"] for r in rows) else "FAIL"),
        "- No unnecessary Executor on read-only work: "
        + ("100%" if all(r["no_unnecessary_agents"] for r in rows) else "FAIL"),
        "",
        "| Case | Subtasks | Bounded | Role/capability | Budget | No unnecessary agent |",
        "|---|---:|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['subtasks']} | {row['bounded']} | "
            f"{row['role_capability'] and row['executable']} | "
            f"{row['budget']} | {row['no_unnecessary_agents']} |"
        )
    lines.extend(["", "```json", json.dumps(out, ensure_ascii=False, indent=2), "```", ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"PLANNER CALIBRATION: {'PASS' if gate else 'FAIL'} {out['passed']}/{out['total']}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
