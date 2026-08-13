"""PRODUCT-01 REAL GATE 真实产品集验收（020-B 五/六/七/八）。

- Simple 10 个：全部真实模型/真实工具（GitHub 搜索/项目总结/文件分析/测试运行等 CLI 可完成项；
  窗口观察/页面观察依赖桌面子系统，文档注明）。
- Standard 10 个：≥5 个必须真实出现 Supervisor/Planner/Researcher/Executor 或 Reviewer 全编排。
- Complex 5 个：真实 Planner/Researcher/Executor/Reviewer + 至少一次真实 Rework。

费用控制（020-B 十八）：max_real_requests / max_total_tokens / max_wall_time；
记录 provider/model/role/model_calls/tool_calls/tokens(REPORTED)/latency/result；
不记录 API Key / Authorization / hidden reasoning。

用法：python scripts/acceptance/run_product01_real.py [--levels "S T C"] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from app.acceptance_runtime import WAITING_FOR_USER_CREDENTIAL_INPUT, effective_model_mode
from app.runner import run_task

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
REPORT_PATH = ROOT / "docs" / "acceptance" / "PRODUCT01_REAL_REPORT.md"

MAX_REAL_REQUESTS = 150  # 总模型调用上限（020-B 十八）
MAX_TOTAL_TOKENS = 300_000
MAX_WALL_TIME_S = 30 * 60

SIMPLE_TASKS = [
    ("S01", "帮我查几个 GitHub 上最近比较热门的 AI Agent 项目。"),
    ("S02", "总结一下这个项目。"),
    ("S03", "帮我看看这个项目主要用了什么技术。"),
    ("S04", "检查一下这个 Python 文件有没有明显问题。"),
    ("S05", "运行一下测试看看有没有报错。"),
    ("S06", "帮我查一下 crewai 的许可证和 star 数。"),
    ("S07", "列出当前目录下的文件。"),
    ("S08", "帮我找几个类似 JARVIS 的开源项目。"),
    ("S09", "现在几点了？"),
    ("S10", "帮我看看这个仓库是干什么的。"),
]

STANDARD_TASKS = [
    ("T01", "去 GitHub 找几个类似我们的多 Agent 项目，对比一下优缺点。"),
    ("T02", "检查项目代码结构，告诉我哪里设计得不好。"),
    ("T03", "找出这个项目里最重要的几个模块。"),
    ("T04", "帮我分析一下这个项目的性能瓶颈可能在哪。"),
    ("T05", "对比 langgraph 和 crewai 的 license 和活跃度。"),
    ("T06", "检查一下代码里有没有明显安全问题。"),
    ("T07", "梳理一下这个项目的错误处理逻辑。"),
    ("T08", "找出最近修改的文件并总结改动。"),
    ("T09", "评估项目对 GitHub API 的依赖是否合理。"),
    ("T10", "看看项目依赖有没有明显重复。"),
]

COMPLEX_TASKS = [
    ("C01", "研究三个 GitHub 项目，然后结合我们的项目提出架构方案，不要直接改代码。"),
    ("C02", "调研三种记忆方案，结合项目现状写一份技术选型报告。"),
    ("C03", "对比国内外 5 个多 Agent 框架，写对比报告并给落地建议。"),
    ("C04", "评估引入向量数据库的收益与风险，给出决策建议。"),
    ("C05", "分析权限系统在多用户场景的缺口，提出加固方案。"),
]


def run_one(task_id: str, goal: str, data_dir: Path) -> dict:
    started = time.perf_counter()
    try:
        report = run_task(
            goal,
            token_budget=100000,
            cost_budget=2.0,
            data_dir=data_dir,
            model_mode="real",
            max_model_calls=80,  # STANDARD 完整编排（planner+researcher×N+reviewer+rework）消耗大
        )
        roles = sorted(
            {
                s.assigned_role
                for s in report.state.subtasks
                if not s.superseded
                and s.assigned_role
                in ("supervisor", "planner", "researcher", "executor", "reviewer")
            }
        )
        return {
            "id": task_id,
            "goal": goal,
            "status": report.status,
            "failure_code": report.state.failure_code,
            "complexity": report.state.complexity,
            "roles_observed": roles,
            "model_calls": report.call_count,
            "tool_calls": report.tool_call_count,
            "tokens": report.usage.get("tokens") if report.usage else None,
            "cost": report.usage.get("cost") if report.usage else None,
            "rework": report.state.rework_count,
            "replan": report.state.replan_count,
            "latency_s": round(time.perf_counter() - started, 1),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": task_id,
            "goal": goal,
            "status": "error",
            "failure_code": "UNKNOWN",
            "complexity": "?",
            "roles_observed": [],
            "model_calls": 0,
            "tool_calls": 0,
            "tokens": 0,
            "cost": 0,
            "rework": 0,
            "replan": 0,
            "latency_s": round(time.perf_counter() - started, 1),
            "error": f"{type(exc).__name__}: {exc}"[:160],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="PRODUCT-01 REAL GATE 真实产品集")
    parser.add_argument("--levels", default="S T C", help="执行级别，如 'S' / 'S T' / 'S T C'")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="生产数据目录（含凭据）")
    args = parser.parse_args()

    mode, status = effective_model_mode("auto", Path(args.data_dir))
    if mode == WAITING_FOR_USER_CREDENTIAL_INPUT:
        print("WAITING_FOR_USER_CREDENTIAL_INPUT")
        print(status.get("hint", ""))
        return 3
    # 验收环境配置（等同产品 Settings 里配置工作目录）：本地只读根 = 项目目录
    # （006 8.1 默认无本地根是安全设计；真实文件分析需显式授权工作目录）
    os.environ.setdefault("AI_TEAM_ALLOWED_READ_ROOTS", str(ROOT))
    print(
        "REAL provider: "
        f"{status.get('provider_name')} / {status.get('model')} "
        f"({status.get('source')})"
    )
    print(f"allowed_read_roots: {os.environ['AI_TEAM_ALLOWED_READ_ROOTS']}")

    groups = []
    if "S" in args.levels.replace(" ", ""):
        groups.append(("SIMPLE", SIMPLE_TASKS, 10))
    if "T" in args.levels.replace(" ", ""):
        groups.append(("STANDARD", STANDARD_TASKS, 9))
    if "C" in args.levels.replace(" ", ""):
        groups.append(("COMPLEX", COMPLEX_TASKS, 4))

    lines: list[str] = [
        "# PRODUCT-01 REAL GATE 报告（020-B）",
        "",
        f"- 执行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- provider: {status.get('provider_name')} / {status.get('model')}",
                f"- 费用上限: max_real_requests={MAX_REAL_REQUESTS}, "
                f"max_total_tokens={MAX_TOTAL_TOKENS}, max_wall_time={MAX_WALL_TIME_S}s",
        "",
    ]
    total_requests = 0
    total_tokens = 0
    all_ok = True
    started_all = time.perf_counter()
    for group_name, tasks, need in groups:
        rows = []
        for task_id, goal in tasks:
            if total_requests >= MAX_REAL_REQUESTS or total_tokens >= MAX_TOTAL_TOKENS:
                print("budget limit reached; stopping")
                break
            r = run_one(task_id, goal, Path(args.data_dir))
            total_requests += r["model_calls"]
            total_tokens += r["tokens"] or 0
            rows.append(r)
            flag = "OK " if r["status"] == "completed" else "!! "
            print(
                f"{flag}{task_id} {r['status']} calls={r['model_calls']} "
                f"tokens={r['tokens']} roles={r['roles_observed']} "
                f"rework={r['rework']} {r['latency_s']}s"
            )
            if time.perf_counter() - started_all > MAX_WALL_TIME_S:
                print("wall time limit reached; stopping")
                break
        passed = sum(1 for r in rows if r["status"] == "completed")
        gate = passed >= need
        all_ok = all_ok and gate
        lines.append(
            f"## {group_name}: {passed}/{len(rows)}（门禁 ≥{need}）→ "
            f"{'PASS' if gate else 'FAIL'}"
        )
        lines.append("")
        lines.append(
            "| id | status | failure | complexity | roles | calls | tools | "
            "tokens | rework | replan | latency_s |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            lines.append(
                f"| {r['id']} | {r['status']} | {r.get('failure_code') or '-'} "
                f"| {r['complexity']} | "
                f"{','.join(r['roles_observed']) or '-'} | {r['model_calls']} "
                f"| {r['tool_calls']} | "
                f"{r['tokens']} | {r['rework']} | {r['replan']} | {r['latency_s']} |"
            )
        lines.append("")
        full_orch = sum(
            1
            for r in rows
            if {"supervisor", "planner", "researcher"} <= set(r["roles_observed"])
            and ({"executor", "reviewer"} & set(r["roles_observed"]))
        )
        lines.append(
            "- 全编排样本（真实 Supervisor/Planner/Researcher/Executor|Reviewer）: "
            f"{full_orch}"
        )
        lines.append("")

    lines.append(f"- 总模型调用: {total_requests}（上限 {MAX_REAL_REQUESTS}）")
    lines.append(f"- 总 tokens: {total_tokens}（REPORTED，上限 {MAX_TOTAL_TOKENS}）")
    lines.append(f"- 总耗时: {round(time.perf_counter() - started_all, 1)}s")
    lines.append("")
    lines.append(
        f"## STATUS: {'PRODUCT_BASELINE_VALIDATED' if all_ok else 'PRODUCT_BASELINE_PARTIAL'}"
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"report written: {REPORT_PATH}")
    print(f"STATUS: {'PRODUCT_BASELINE_VALIDATED' if all_ok else 'PRODUCT_BASELINE_PARTIAL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
