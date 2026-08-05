"""CLI（M3-A）：run / resume / status / trace / providers / provider-health。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import load_settings
from app.core.resume import ResumePayload
from app.core.schemas import ClarificationPayload
from app.gateway.contracts import ProviderError
from app.runner import (
    RunReport,
    dry_run,
    provider_health,
    resume_task,
    run_task,
    status_task,
    trace_task,
)


def _print_report(report: RunReport) -> None:
    print(f"task_id:          {report.task_id}")
    print(f"run_id:           {report.run_id}")
    print(f"status:           {report.status}")
    print(f"final_result:     {report.state.final_result}")
    print(f"usage:            {report.usage}")
    print(f"model_calls:      {report.call_count}")
    print(f"tool_call_count:  {report.tool_call_count}")


def _print_providers(settings) -> None:
    print(f"provider:         {settings.model.provider}")
    print(f"real_enabled:     {settings.model.enable_real}")
    print(f"default_model:    {settings.model.default_model or '(未配置)'}")
    print("role routing:")
    for role, model in settings.routing.role_defaults.items():
        print(f"  {role}: {model or '(继承 default)'}")
    print(f"allowed_models:   {settings.routing.allowed_models}")
    print(f"fallback_models:  {settings.routing.fallback_models}")
    print("(API Key 已配置但绝不显示)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ai-team-os", description="AI Team OS 任务 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="运行一个任务（如 github_compare_team / vague_goal）")
    run.add_argument(
        "goal", help="用户目标（支持场景：github_compare_team / vague_goal / 测试场景名）"
    )
    run.add_argument("--budget-tokens", type=int, default=10000)
    run.add_argument("--budget-cost", type=float, default=1.0)
    run.add_argument("--project-id", default="default")
    run.add_argument("--data-dir", default=None)
    run.add_argument(
        "--model-mode",
        choices=["fake", "real"],
        default="fake",
        help="模型模式（默认 fake，避免意外费用）",
    )
    run.add_argument("--dry-run", action="store_true", help="只显示预计模型调用与预算，不真正调用")
    run.add_argument("--model-override", action="append", default=[], metavar="ROLE=MODEL")
    run.add_argument(
        "--project", default=None, help="本地项目别名（映射到允许根目录子目录，不接收任意绝对路径）"
    )
    run.add_argument("--allowed-domains", default=None, help="允许域名列表（预留，M3-B 不启用）")

    resume = sub.add_parser("resume", help="恢复暂停的任务（澄清挂起时须带 --clarification）")
    resume.add_argument("run_id", help="run_id（= checkpoint thread_id）")
    resume.add_argument(
        "--clarification", default=None, help="澄清答案（ClarificationPayload.answer）"
    )
    resume.add_argument("--data-dir", default=None)

    status = sub.add_parser("status", help="查询任务状态")
    status.add_argument("run_id", help="run_id（= checkpoint thread_id）")
    status.add_argument("--data-dir", default=None)

    trace = sub.add_parser("trace", help="任务运行追踪（完整结构化状态）")
    trace.add_argument("run_id", help="run_id（= checkpoint thread_id）")
    trace.add_argument("--data-dir", default=None)

    sub.add_parser("providers", help="显示 Provider 与角色路由配置")
    sub.add_parser("provider-health", help="Provider 健康状态（不发起真实请求）")
    sub.add_parser("tools", help="列出可用只读工具")
    tools_info = sub.add_parser("tool-info", help="查看单个工具信息")
    tools_info.add_argument("tool", help="工具名")
    sub.add_parser("allowed-read-roots", help="显示本地只读根目录（AI_TEAM_ALLOWED_READ_ROOTS）")
    sub.add_parser("acceptance-status", help="验收状态总览（007 3.3；不显示 Token/Key）")
    acceptance_run_parser = sub.add_parser("acceptance-run", help="单项目真实验收（不混入 pytest）")
    acceptance_run_parser.add_argument(
        "name",
        choices=["real-model", "github-readonly", "web-readonly", "local-readonly"],
    )
    evidence = sub.add_parser("evidence", help="列出任务的 Evidence 摘要")
    evidence.add_argument("run_id", help="run_id（= checkpoint thread_id）")
    evidence.add_argument("--data-dir", default=None)
    evidence_show_parser = sub.add_parser(
        "evidence-show", help="查看 Evidence 原始快照（明确命令）"
    )
    evidence_show_parser.add_argument("evidence_id", help="evidence_id")
    evidence_show_parser.add_argument("--data-dir", default=None)

    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir) if getattr(args, "data_dir", None) else None
    settings = load_settings()

    if args.command == "providers":
        _print_providers(settings)
    elif args.command == "provider-health":
        print(json.dumps(provider_health(settings), ensure_ascii=False, indent=2))
    elif args.command == "tools":
        from app.runner import tool_catalog

        print(json.dumps(tool_catalog(settings), ensure_ascii=False, indent=2))
    elif args.command == "tool-info":
        from app.runner import tool_catalog

        entry = next((t for t in tool_catalog(settings) if t["name"] == args.tool), None)
        if entry is None:
            parser.error(f"unknown tool: {args.tool}")
        print(json.dumps(entry, ensure_ascii=False, indent=2))
    elif args.command == "allowed-read-roots":
        from app.core.config import allowed_read_roots

        roots = allowed_read_roots(settings)
        print(f"allowed_read_roots: {roots or '(未配置，本地文件工具不可用)'}")
    elif args.command == "acceptance-status":
        from app.core.acceptance import acceptance_status

        print(json.dumps(acceptance_status(settings), ensure_ascii=False, indent=2))
    elif args.command == "acceptance-run":
        from app.core.acceptance import acceptance_run

        print(json.dumps(acceptance_run(args.name, settings), ensure_ascii=False, indent=2))
    elif args.command == "evidence":
        from app.runner import evidence_list

        print(
            json.dumps(evidence_list(args.run_id, data_dir=data_dir), ensure_ascii=False, indent=2)
        )
    elif args.command == "evidence-show":
        from app.runner import evidence_show

        print(
            json.dumps(
                evidence_show(args.evidence_id, data_dir=data_dir), ensure_ascii=False, indent=2
            )
        )
    elif args.command == "run":
        if args.budget_tokens <= 0 or args.budget_cost <= 0:
            parser.error("--budget-tokens 与 --budget-cost 必须为正数")
        overrides = {}
        for item in args.model_override:
            role, _, model = item.partition("=")
            overrides[role.strip()] = model.strip()
        if args.project:
            overrides["project_alias"] = args.project
        if args.allowed_domains:
            overrides["allowed_domains"] = args.allowed_domains
        if args.dry_run:
            print(
                json.dumps(
                    dry_run(args.goal, args.budget_tokens, args.budget_cost, settings),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        try:
            _print_report(
                run_task(
                    args.goal,
                    args.budget_tokens,
                    args.budget_cost,
                    args.project_id,
                    data_dir=data_dir,
                    model_mode=args.model_mode,
                    model_overrides=overrides or None,
                    settings=settings,
                )
            )
        except ProviderError as exc:
            # 005 十六：未启用真实调用 / 缺 API Key 等配置错误明确报安全消息
            parser.error(f"model provider error: {exc.safe_message}")
    elif args.command == "resume":
        if args.clarification:
            # 澄清挂起时从 checkpoint 读取 pending_clarification_id 构造 ClarificationPayload
            snapshot = status_task(args.run_id, data_dir=data_dir)
            pending_id = snapshot.state.pending_clarification_id
            if not pending_id:
                parser.error(f"run {args.run_id} 不在澄清挂起状态，--clarification 不适用")
            payload: ResumePayload | ClarificationPayload = ClarificationPayload(
                clarification_id=pending_id, answer=args.clarification
            )
        else:
            payload = ResumePayload(action="continue")
        _print_report(
            resume_task(args.run_id, payload=payload, data_dir=data_dir, settings=settings)
        )
    elif args.command == "status":
        _print_report(status_task(args.run_id, data_dir=data_dir))
    elif args.command == "trace":
        print(json.dumps(trace_task(args.run_id, data_dir=data_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
