"""CLI（M1 + 003-A 二）：run / resume / status。"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.resume import ResumePayload
from app.runner import RunReport, resume_task, run_task, status_task


def _print_report(report: RunReport) -> None:
    print(f"task_id:          {report.task_id}")
    print(f"run_id:           {report.run_id}")
    print(f"status:           {report.status}")
    print(f"final_result:     {report.state.final_result}")
    print(f"usage:            {report.usage}")
    print(f"model_calls:      {report.call_count}")
    print(f"tool_call_count:  {report.tool_call_count}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ai-team-os", description="AI Team OS 任务 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="运行一个任务")
    run.add_argument("goal", help="用户目标")
    run.add_argument("--budget-tokens", type=int, default=10000)
    run.add_argument("--budget-cost", type=float, default=1.0)
    run.add_argument("--project-id", default="default")
    run.add_argument("--pause-after", default=None, help="在节点边界暂停（当前支持 agent）")
    run.add_argument("--data-dir", default=None)

    resume = sub.add_parser("resume", help="恢复暂停的任务")
    resume.add_argument("run_id", help="run_id（= checkpoint thread_id）")
    resume.add_argument("--action", default="continue")
    resume.add_argument("--data-dir", default=None)

    status = sub.add_parser("status", help="查询任务状态")
    status.add_argument("run_id", help="run_id（= checkpoint thread_id）")
    status.add_argument("--data-dir", default=None)

    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir) if getattr(args, "data_dir", None) else None

    if args.command == "run":
        if args.budget_tokens <= 0 or args.budget_cost <= 0:
            parser.error("--budget-tokens 与 --budget-cost 必须为正数")
        _print_report(
            run_task(
                args.goal,
                args.budget_tokens,
                args.budget_cost,
                args.project_id,
                data_dir=data_dir,
                pause_after=args.pause_after,
            )
        )
    elif args.command == "resume":
        _print_report(
            resume_task(args.run_id, payload=ResumePayload(action=args.action), data_dir=data_dir)
        )
    elif args.command == "status":
        _print_report(status_task(args.run_id, data_dir=data_dir))


if __name__ == "__main__":
    main()
