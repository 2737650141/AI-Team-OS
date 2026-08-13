"""PRODUCT-02 expanded real-provider acceptance after the immutable 9/9 core gate.

Runs selected cases from REAL_WORLD_TASK_SUITE without prompt rewriting, mocking,
or fake fallback. Results are checkpoint/audit-backed and written after every case.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

from run_product01 import SUITE_PATH, parse_suite

from app.acceptance_runtime import WAITING_FOR_USER_CREDENTIAL_INPUT, effective_model_mode
from app.conversation.service import run_conversation_turn
from app.runner import run_task

ROOT = Path(__file__).resolve().parents[2]
CORE_REPORT = ROOT / "docs" / "acceptance" / "PRODUCT02_CORE_BENCHMARK.md"
REPORT = ROOT / "docs" / "acceptance" / "PRODUCT02_EXPANDED_BENCHMARK.md"
DEFAULT_DATA = ROOT / "data"

CASE_IDS = {
    # Context-dependent A07 ("this Python file") is intentionally excluded:
    # without an attached/current file the correct product behavior is clarify,
    # not guessing a path. These ten cases are self-contained in this runtime.
    "simple": ["A01", "A04", "A05", "A06", "A08", "A10", "A11", "A12", "A13", "A15"],
    "standard": ["B01", "B03", "B05", "B06", "B07", "B09", "B11", "B15", "B19", "B20"],
    "complex": ["C01", "C05", "C07", "C11", "C15"],
}

TEN_TURN = [
    "找几个最近热门的 Agent 项目",
    "第二个详细看看",
    "跟我们的项目比较一下",
    "哪些东西值得我们借鉴",
    "先别改代码",
    "那先写个方案",
    "继续",
    "把第一项实施",
    "看一下结果",
    "还有没有问题",
]


def _core_gate_passed() -> bool:
    return CORE_REPORT.exists() and "Gate: PASS (9/9)" in CORE_REPORT.read_text(encoding="utf-8")


def _failure(report) -> dict:
    state = report.state
    return {
        "stage": state.failure_details.get("failed_stage") or "unknown",
        "agent": state.failure_details.get("agent") or "unknown",
        "code": state.failure_code or "unknown",
        "root_cause": state.failure_details.get("root_cause") or state.final_result,
        "recovery": state.failure_details.get("recovery_attempt") or "none",
        "decision": state.failure_details.get("final_decision") or state.current_status,
    }


def _run_case(case_id: str, goal: str, data_dir: Path) -> dict:
    started = time.perf_counter()
    try:
        report = run_task(
            goal,
            token_budget=60000,
            cost_budget=1.5,
            data_dir=data_dir,
            model_mode="real",
            max_model_calls=20,
        )
        active = [item for item in report.state.subtasks if not item.superseded]
        result_nonempty = bool((report.state.final_result or "").strip())
        passed = report.status == "completed" and result_nonempty
        return {
            "id": case_id,
            "goal": goal,
            "passed": passed,
            "status": report.status,
            "failure": None if passed else _failure(report),
            "task_id": report.task_id,
            "run_id": report.run_id,
            "complexity": report.state.complexity,
            "shape": report.state.task_shape,
            "subtasks": len(active),
            "roles": sorted({item.assigned_role for item in active}),
            "calls": int(report.usage.get("calls", 0)),
            "tokens": int(report.usage.get("tokens", 0)),
            "cost": float(report.usage.get("cost", 0)),
            "tools": report.tool_call_count,
            "rework": report.state.rework_count,
            "replan": report.state.replan_count,
            "latency": round(time.perf_counter() - started, 2),
            "fake_calls": 0,
        }
    except Exception as exc:  # black-box acceptance must retain every failure
        return {
            "id": case_id,
            "goal": goal,
            "passed": False,
            "status": "error",
            "failure": {
                "stage": "runtime",
                "agent": "unknown",
                "code": type(exc).__name__,
                "root_cause": str(exc)[:500],
                "recovery": "none",
                "decision": "failed",
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


def _p95(values: list[int]) -> float:
    if not values:
        return 0.0
    return (
        float(statistics.quantiles(values, n=20, method="inclusive")[18])
        if len(values) > 1
        else float(values[0])
    )


def _metrics(rows: list[dict]) -> dict:
    calls = [row["calls"] for row in rows]
    return {
        "passed": sum(bool(row["passed"]) for row in rows),
        "total": len(rows),
        "average_calls": round(statistics.mean(calls), 2) if calls else 0,
        "median_calls": round(statistics.median(calls), 2) if calls else 0,
        "p95_calls": round(_p95(calls), 2),
        "average_tokens": round(statistics.mean([row["tokens"] for row in rows]), 2) if rows else 0,
        "average_rework": round(statistics.mean([row["rework"] for row in rows]), 2) if rows else 0,
        "average_latency": round(statistics.mean([row["latency"] for row in rows]), 2)
        if rows
        else 0,
    }


def _gate(suite: str, metrics: dict) -> bool:
    if suite == "simple":
        return metrics["passed"] == 10 and metrics["total"] == 10 and metrics["average_calls"] <= 4
    if suite == "standard":
        return (
            metrics["passed"] >= 9
            and metrics["total"] == 10
            and metrics["average_calls"] <= 12
            and metrics["p95_calls"] <= 20
            and metrics["average_rework"] <= 1
        )
    if suite == "complex":
        return metrics["passed"] >= 4 and metrics["total"] == 5
    if suite == "session":
        return metrics["passed"] == 10 and metrics["total"] == 10
    return False


def _write(provider: dict, suites: dict[str, list[dict]]) -> None:
    summary = {
        name: {**_metrics(rows), "gate": _gate(name, _metrics(rows))}
        for name, rows in suites.items()
    }
    payload = {
        "phase": "PRODUCT-02",
        "provider": provider.get("provider_name"),
        "model": provider.get("model"),
        "model_mode": "real",
        "fake_fallback": 0,
        "executed": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "suites": suites,
    }
    lines = [
        "# PRODUCT-02 Expanded Benchmark",
        "",
        f"- Executed: {payload['executed']}",
        f"- Provider / model: {payload['provider']} / {payload['model'] or ''}",
        "- Model mode: real",
        "- Fake fallback: 0",
        "",
    ]
    for name, rows in suites.items():
        m = summary[name]
        lines.extend(
            [
                f"## {name.upper()}",
                "",
                f"- Gate: {'PASS' if m['gate'] else 'FAIL'} ({m['passed']}/{m['total']})",
                f"- Calls avg / median / P95: {m['average_calls']} / "
                f"{m['median_calls']} / {m['p95_calls']}",
                f"- Average tokens / rework / latency: {m['average_tokens']} / "
                f"{m['average_rework']} / {m['average_latency']}s",
                "",
                "| Case | Result | Complexity | Shape | Calls | Tokens | Rework | Latency |",
                "|---|---|---|---|---:|---:|---:|---:|",
            ]
        )
        for row in rows:
            lines.append(
                f"| {row['id']} | {'PASS' if row['passed'] else 'FAIL'} | "
                f"{row.get('complexity', '-')} | {row.get('shape', '-')} | "
                f"{row['calls']} | {row['tokens']} | {row['rework']} | "
                f"{row['latency']} |"
            )
            if row.get("failure"):
                lines.append(
                    f"\nFailure {row['id']}: `{json.dumps(row['failure'], ensure_ascii=False)}`\n"
                )
        lines.append("")
    lines.extend(["```json", json.dumps(payload, ensure_ascii=False, indent=2), "```", ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def _run_session(data_dir: Path, provider: dict, suites: dict[str, list[dict]]) -> list[dict]:
    rows: list[dict] = []
    session_id = f"product02-real-{int(time.time())}"
    for index, user_input in enumerate(TEN_TURN, start=1):
        started = time.perf_counter()
        try:
            _session, result = run_conversation_turn(
                session_id,
                user_input,
                data_dir,
                model_mode="real",
                token_budget=60000,
                cost_budget=1.5,
                project_alias="sample-python",
            )
            acceptable = result.get("status") in {"completed", "confirmed"}
            row = {
                "id": f"T{index:02d}",
                "goal": user_input,
                "passed": acceptable and result.get("action") != "clarify",
                "status": result.get("status"),
                "failure": None,
                "task_id": result.get("task_id"),
                "run_id": result.get("run_id"),
                "complexity": result.get("complexity", "conversation"),
                "shape": "conversation",
                "subtasks": 0,
                "roles": [],
                "calls": int(result.get("model_calls") or 0),
                "tokens": int(result.get("tokens") or 0),
                "cost": 0.0,
                "tools": int(result.get("tool_calls") or 0),
                "rework": int(result.get("rework") or 0),
                "replan": int(result.get("replan") or 0),
                "latency": round(time.perf_counter() - started, 2),
                "fake_calls": 0,
            }
            if not row["passed"]:
                row["failure"] = {
                    "code": result.get("failure_code") or "CONTEXT_FAILURE",
                    "root_cause": result.get("summary", ""),
                }
        except Exception as exc:
            row = {
                "id": f"T{index:02d}",
                "goal": user_input,
                "passed": False,
                "status": "error",
                "failure": {"code": type(exc).__name__, "root_cause": str(exc)[:500]},
                "calls": 0,
                "tokens": 0,
                "cost": 0.0,
                "tools": 0,
                "rework": 0,
                "replan": 0,
                "latency": round(time.perf_counter() - started, 2),
                "fake_calls": 0,
            }
        rows.append(row)
        suites["session"] = rows
        _write(provider, suites)
        print(
            f"SESSION {row['id']}: {'PASS' if row['passed'] else 'FAIL'} "
            f"calls={row['calls']} tokens={row['tokens']}",
            flush=True,
        )
        if not row["passed"]:
            break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite", choices=["simple", "standard", "complex", "session", "all"], required=True
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--complex-count", type=int, choices=[3, 5], default=5)
    args = parser.parse_args()
    if not _core_gate_passed():
        print("REFUSED: PRODUCT-02 core 9/9 gate has not passed")
        return 2
    mode, provider = effective_model_mode("real", args.data_dir)
    if mode == WAITING_FOR_USER_CREDENTIAL_INPUT:
        print("WAITING_FOR_USER_CREDENTIAL_INPUT")
        return 3
    os.environ.setdefault(
        "AI_TEAM_ALLOWED_READ_ROOTS",
        f"{ROOT};{ROOT / 'fixtures'}",
    )
    existing: dict[str, list[dict]] = {}
    if REPORT.exists():
        text = REPORT.read_text(encoding="utf-8")
        if "```json" in text:
            try:
                existing = json.loads(text.split("```json", 1)[1].split("```", 1)[0])["suites"]
            except (KeyError, ValueError, json.JSONDecodeError):
                existing = {}
    selected = ["simple", "standard", "complex", "session"] if args.suite == "all" else [args.suite]
    cases = {case.id: case for case in parse_suite(SUITE_PATH)}
    for suite in selected:
        if suite == "session":
            rows = _run_session(args.data_dir, provider, existing)
        else:
            rows = []
            case_ids = CASE_IDS[suite]
            if suite == "complex":
                case_ids = case_ids[: args.complex_count]
            for case_id in case_ids:
                row = _run_case(case_id, cases[case_id].user_input, args.data_dir)
                rows.append(row)
                existing[suite] = rows
                _write(provider, existing)
                print(
                    f"{suite.upper()} {case_id}: "
                    f"{'PASS' if row['passed'] else 'FAIL'} "
                    f"calls={row['calls']} tokens={row['tokens']}",
                    flush=True,
                )
            existing[suite] = rows
        metrics = _metrics(rows)
        passed = (
            metrics["passed"] >= 2 and metrics["total"] == 3
            if suite == "complex" and args.complex_count == 3
            else _gate(suite, metrics)
        )
        print(f"{suite.upper()} GATE: {'PASS' if passed else 'FAIL'} {metrics}", flush=True)
        if not passed:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
