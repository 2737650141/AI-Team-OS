"""CLI（M1 最小）。"""

from __future__ import annotations

import argparse
import sys

from app.runner import run_task


def main(argv: list[str] | None = None) -> None:
    # Windows 控制台默认 GBK，统一 UTF-8 输出
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="ai-team-os", description="AI Team OS 任务 CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="运行一个任务")
    run.add_argument("goal", help="用户目标")
    run.add_argument("--budget-tokens", type=int, default=10000)
    run.add_argument("--budget-cost", type=float, default=1.0)
    run.add_argument("--project-id", default="default")
    args = parser.parse_args(argv)

    if args.command == "run":
        report = run_task(
            args.goal,
            token_budget=args.budget_tokens,
            cost_budget=args.budget_cost,
            project_id=args.project_id,
        )
        print(f"task_id: {report.task_id}")
        print(f"status:  {report.status}")
        print(f"result:  {report.state.final_result}")
        print(f"usage:   {report.usage}")
        print(f"calls:   {report.call_count}")


if __name__ == "__main__":
    main()
