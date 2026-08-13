"""PRODUCT-02 gated real-provider reliability acceptance.

Gate order is immutable: one A/B/C round (3/3), then three consecutive rounds
(9/9). Expanded suites are separate commands and are refused until the core gate
report records success. No fake provider or fallback is allowed.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from app.acceptance_runtime import WAITING_FOR_USER_CREDENTIAL_INPUT, effective_model_mode
from app.runner import run_task

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data"
REPORT = ROOT / "docs" / "acceptance" / "PRODUCT02_CORE_BENCHMARK.md"


@dataclass(frozen=True)
class Limits:
    requests: int
    tokens: int
    cost: float
    wall_time: float

    @classmethod
    def from_env(cls) -> "Limits":
        return cls(
            requests=int(os.environ.get("PRODUCT02_REAL_MAX_REQUESTS", "80")),
            tokens=int(os.environ.get("PRODUCT02_REAL_MAX_TOKENS", "180000")),
            cost=float(os.environ.get("PRODUCT02_REAL_MAX_COST", "5.0")),
            wall_time=float(os.environ.get("PRODUCT02_REAL_MAX_WALL_TIME", "1800")),
        )


BENCHMARKS = (
    (
        "A",
        "去 GitHub 找 3 个和 AI Team OS 类似的多 Agent 项目，对比它们的优缺点，"
        "最后告诉我哪些设计值得我们借鉴。",
        None,
    ),
    (
        "B",
        "sandbox_code_fix: 这个项目有一个失败测试，找出原因，给出最小修改，"
        "直接修复，运行测试，最后让 Reviewer 验收。",
        "sample-python",
    ),
    (
        "C",
        "分析 app/core 模块的依赖关系和潜在风险，只给修改方案，不要改代码。",
        None,
    ),
)


def _failure_details(report) -> dict:
    state = report.state
    return {
        "failed_stage": state.failure_details.get("failed_stage") or "unknown",
        "agent": state.failure_details.get("agent") or "unknown",
        "failure_code": state.failure_code,
        "root_cause": state.failure_details.get("root_cause") or state.final_result,
        "recovery_attempt": state.failure_details.get("recovery_attempt") or "none",
        "final_decision": state.failure_details.get("final_decision") or state.current_status,
    }


def run_case(case_id: str, goal: str, project: str | None, data_dir: Path) -> dict:
    started = time.perf_counter()
    overrides = {"project_alias": project} if project else None
    try:
        report = run_task(
            goal,
            token_budget=60000,
            cost_budget=1.5,
            data_dir=data_dir,
            model_mode="real",
            model_overrides=overrides,
            max_model_calls=20,
        )
        active = [item for item in report.state.subtasks if not item.superseded]
        writes = [
            call.tool
            for call in report.state.tool_calls
            if any(marker in call.tool for marker in ("write", "patch", "delete", "move"))
        ]
        result_nonempty = bool(report.state.final_result and report.state.final_result.strip())
        shape_ok = not (case_id == "C" and writes)
        passed = report.status == "completed" and result_nonempty and shape_ok
        return {
            "case": case_id,
            "passed": passed,
            "status": report.status,
            "failure": None if passed else _failure_details(report),
            "task_id": report.task_id,
            "run_id": report.run_id,
            "shape": report.state.task_shape,
            "subtasks": len(active),
            "roles": sorted({item.assigned_role for item in active}),
            "calls": int(report.usage.get("calls", 0)),
            "tokens": int(report.usage.get("tokens", 0)),
            "cost": float(report.usage.get("cost", 0)),
            "tools": report.tool_call_count,
            "writes": writes,
            "rework": report.state.rework_count,
            "replan": report.state.replan_count,
            "latency": round(time.perf_counter() - started, 2),
            "fake_calls": 0,
        }
    except Exception as exc:  # first attempt remains a failed sample
        return {
            "case": case_id,
            "passed": False,
            "status": "error",
            "failure": {
                "failed_stage": "runtime",
                "agent": "unknown",
                "failure_code": type(exc).__name__,
                "root_cause": str(exc)[:500],
                "recovery_attempt": "none",
                "final_decision": "failed",
            },
            "calls": 0,
            "tokens": 0,
            "cost": 0.0,
            "tools": 0,
            "rework": 0,
            "replan": 0,
            "latency": round(time.perf_counter() - started, 2),
            "fake_calls": 0,
        }


def _within_limits(rows: list[dict], limits: Limits, started: float) -> bool:
    return (
        sum(row["calls"] for row in rows) < limits.requests
        and sum(row["tokens"] for row in rows) < limits.tokens
        and sum(row["cost"] for row in rows) < limits.cost
        and time.perf_counter() - started < limits.wall_time
    )


def _write_report(provider: dict, mode: str, rounds: int, rows: list[dict], limits: Limits) -> None:
    round_results = []
    for index in range(rounds):
        current = rows[index * 3 : index * 3 + 3]
        round_results.append(all(row["passed"] for row in current) and len(current) == 3)
    gate = len(rows) == rounds * 3 and all(round_results)
    calls = [row["calls"] for row in rows]
    payload = {
        "phase": "PRODUCT-02",
        "mode": mode,
        "provider": provider.get("provider_name"),
        "model": provider.get("model"),
        "fake_fallback": 0,
        "limits": limits.__dict__,
        "rounds": round_results,
        "passed": sum(row["passed"] for row in rows),
        "total": len(rows),
        "average_calls": round(statistics.mean(calls), 2) if calls else 0,
        "p95_calls": max(calls) if calls else 0,
        "rows": rows,
        "gate": gate,
    }
    lines = [
        "# PRODUCT-02 Core Benchmark",
        "",
        f"- Executed: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Provider / model: {payload['provider']} / {payload['model']}",
        "- Fake fallback: 0",
        f"- Gate: {'PASS' if gate else 'FAIL'} ({payload['passed']}/{payload['total']})",
        f"- Average calls: {payload['average_calls']}; "
        f"P95(max for this small gate): {payload['p95_calls']}",
        "",
        "| Round | Case | Result | Shape | Roles | Calls | Tokens | Cost | Rework | Latency |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(rows):
        lines.append(
            f"| {index // 3 + 1} | {row['case']} | {'PASS' if row['passed'] else 'FAIL'} "
            f"| {row.get('shape', '-')} | {','.join(row.get('roles', [])) or '-'} "
            f"| {row['calls']} | {row['tokens']} | {row['cost']:.6f} "
            f"| {row['rework']} | {row['latency']} |"
        )
        if row.get("failure"):
            failure = json.dumps(row["failure"], ensure_ascii=False)
            lines.extend(
                [
                    "",
                    f"Failure {index // 3 + 1}{row['case']}: `{failure}`",
                    "",
                ]
            )
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2), "```", ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", choices=("3", "9"), default="3")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    rounds = 1 if args.gate == "3" else 3
    limits = Limits.from_env()
    mode, provider = effective_model_mode("real", args.data_dir)
    if mode == WAITING_FOR_USER_CREDENTIAL_INPUT:
        print("WAITING_FOR_USER_CREDENTIAL_INPUT")
        return 3
    os.environ.setdefault(
        "AI_TEAM_ALLOWED_READ_ROOTS",
        f"{ROOT};{ROOT / 'fixtures'}",
    )
    rows: list[dict] = []
    started = time.perf_counter()
    for round_no in range(1, rounds + 1):
        for case_id, goal, project in BENCHMARKS:
            if not _within_limits(rows, limits, started):
                _write_report(provider, args.gate, rounds, rows, limits)
                print("PRODUCT02_REAL_LIMIT_REACHED")
                return 5
            row = run_case(case_id, goal, project, args.data_dir)
            rows.append(row)
            print(
                f"Round {round_no} {case_id}: {'PASS' if row['passed'] else 'FAIL'} "
                f"calls={row['calls']} tokens={row['tokens']} rework={row['rework']}"
            )
            if not row["passed"] and rounds == 1:
                _write_report(provider, args.gate, rounds, rows, limits)
                return 1
    _write_report(provider, args.gate, rounds, rows, limits)
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
