"""CLI（M3-A）：run / resume / status / trace / providers / provider-health。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import load_settings
from app.core.resume import ResumePayload
from app.core.schemas import ApprovalPayload, ClarificationPayload
from app.gateway.contracts import ProviderError
from app.runner import (
    RunReport,
    approval_show,
    approvals_of,
    artifact_show,
    artifacts_of,
    diff_of,
    dry_run,
    provider_health,
    resume_task,
    run_task,
    status_task,
    trace_task,
    workspace_status,
    workspaces,
)


def _approval_resume_payload(
    approval_id: str, decision: str, reason: str | None
) -> ApprovalPayload:
    """从 run 的 checkpoint 定位 pending approval 并构造恢复值（approve/reject）。"""
    return ApprovalPayload(approval_id=approval_id, decision=decision, reason=reason)  # type: ignore[arg-type]


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
    # 007 十六：沙箱工作区/审批/Artifact/回滚
    sub.add_parser("workspaces", help="列出任务工作区")
    workspace_status_parser = sub.add_parser("workspace-status", help="单个工作区状态")
    workspace_status_parser.add_argument("task_id")
    diff_cmd = sub.add_parser("diff", help="任务最新 Diff")
    diff_cmd.add_argument("run_id")
    approvals_parser = sub.add_parser("approvals", help="任务的审批列表")
    approvals_parser.add_argument("run_id")
    approval_show_parser = sub.add_parser("approval-show", help="单个审批详情")
    approval_show_parser.add_argument("approval_id")
    approve_parser = sub.add_parser("approve", help="批准审批并恢复任务（007 5.4）")
    approve_parser.add_argument("run_id")
    approve_parser.add_argument("approval_id")
    reject_parser = sub.add_parser("reject", help="拒绝审批并恢复任务（不应用补丁）")
    reject_parser.add_argument("run_id")
    reject_parser.add_argument("approval_id")
    reject_parser.add_argument("--reason", default=None)
    artifacts_cmd = sub.add_parser("artifacts", help="任务的 Artifact 列表")
    artifacts_cmd.add_argument("run_id")
    artifact_show_parser = sub.add_parser("artifact-show", help="单个 Artifact 内容")
    artifact_show_parser.add_argument("artifact_id")
    rollback_parser = sub.add_parser(
        "rollback", help="回滚指定 Patch（缺省内部创建并批准回滚审批）"
    )
    rollback_parser.add_argument("run_id")
    rollback_parser.add_argument("--patch", required=True, help="目标 Patch 的 approval_id")
    rollback_parser.add_argument(
        "--approval", default=None, help="已批准的回滚审批 approval_id（缺省：本命令即批准）"
    )
    for p in (
        workspace_status_parser,
        diff_cmd,
        approvals_parser,
        approval_show_parser,
        approve_parser,
        reject_parser,
        artifacts_cmd,
        artifact_show_parser,
        rollback_parser,
    ):
        p.add_argument("--data-dir", default=None)
    evidence = sub.add_parser("evidence", help="列出任务的 Evidence 摘要")
    evidence.add_argument("run_id", help="run_id（= checkpoint thread_id）")
    evidence.add_argument("--data-dir", default=None)
    evidence_show_parser = sub.add_parser(
        "evidence-show", help="查看 Evidence 原始快照（明确命令）"
    )
    evidence_show_parser.add_argument("evidence_id", help="evidence_id")
    evidence_show_parser.add_argument("--data-dir", default=None)

    # 013 M4-A：高级记忆管理；普通用户优先使用 Memory Center。
    memories_parser = sub.add_parser("memories", help="列出受治理的记忆")
    memories_parser.add_argument("--project-id", default=None)
    memory_show_parser = sub.add_parser("memory-show", help="查看单条记忆")
    memory_show_parser.add_argument("memory_id")
    memory_search_parser = sub.add_parser("memory-search", help="全文检索记忆")
    memory_search_parser.add_argument("query")
    memory_search_parser.add_argument("--project-id", default=None)
    sub.add_parser("memory-proposals", help="列出待确认记忆建议")
    memory_confirm_parser = sub.add_parser("memory-confirm", help="确认记忆建议")
    memory_confirm_parser.add_argument("proposal_id")
    memory_reject_parser = sub.add_parser("memory-reject", help="拒绝记忆建议")
    memory_reject_parser.add_argument("proposal_id")
    memory_edit_parser = sub.add_parser("memory-edit", help="编辑并确认记忆建议")
    memory_edit_parser.add_argument("proposal_id")
    memory_edit_parser.add_argument("value")
    memory_forget_parser = sub.add_parser("memory-forget", help="真正遗忘一条记忆")
    memory_forget_parser.add_argument("memory_id")
    sub.add_parser("memory-export", help="导出非 Secret、未遗忘的记忆")
    sub.add_parser("memory-health", help="检查记忆库完整性")
    for p in (
        memories_parser,
        memory_show_parser,
        memory_search_parser,
        memory_confirm_parser,
        memory_reject_parser,
        memory_edit_parser,
        memory_forget_parser,
    ):
        p.add_argument("--data-dir", default=None)

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
    elif args.command == "workspaces":
        print(json.dumps(workspaces(data_dir), ensure_ascii=False, indent=2))
    elif args.command == "workspace-status":
        print(json.dumps(workspace_status(args.task_id, data_dir), ensure_ascii=False, indent=2))
    elif args.command == "diff":
        print(json.dumps(diff_of(args.run_id, data_dir), ensure_ascii=False, indent=2))
    elif args.command == "approvals":
        print(json.dumps(approvals_of(args.run_id, data_dir), ensure_ascii=False, indent=2))
    elif args.command == "approval-show":
        print(json.dumps(approval_show(args.approval_id, data_dir), ensure_ascii=False, indent=2))
    elif args.command == "approve":
        # 007 5.4：approve → 决策落盘 → 恢复任务
        approval_payload = _approval_resume_payload(args.approval_id, "approved", None)
        _print_report(
            resume_task(args.run_id, payload=approval_payload, data_dir=data_dir, settings=settings)
        )
    elif args.command == "reject":
        approval_payload = _approval_resume_payload(args.approval_id, "rejected", args.reason)
        _print_report(
            resume_task(args.run_id, payload=approval_payload, data_dir=data_dir, settings=settings)
        )
    elif args.command == "artifacts":
        print(json.dumps(artifacts_of(args.run_id, data_dir), ensure_ascii=False, indent=2))
    elif args.command == "artifact-show":
        print(json.dumps(artifact_show(args.artifact_id, data_dir), ensure_ascii=False, indent=2))
    elif args.command == "rollback":
        from app.runner import rollback as _rollback

        try:
            print(
                json.dumps(
                    _rollback(args.run_id, args.patch, args.approval, data_dir),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(exc)}))
            raise SystemExit(1)
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
    elif args.command.startswith("memory") or args.command == "memories":
        from app.memory.service import MemoryService

        memory = MemoryService.from_data_dir(data_dir or Path("data"))
        memory_payload: object
        if args.command == "memories":
            memory_payload = [
                item.model_dump(mode="json")
                for item in memory.store.list(
                    project_id=args.project_id,
                    include_global=args.project_id is not None,
                )
            ]
        elif args.command == "memory-show":
            record = memory.store.get(args.memory_id)
            if record is None:
                parser.error(f"memory not found: {args.memory_id}")
            memory_payload = record.model_dump(mode="json")
        elif args.command == "memory-search":
            memory_payload = [
                item.model_dump(mode="json")
                for item in memory.store.search(args.query, project_id=args.project_id)
            ]
        elif args.command == "memory-proposals":
            memory_payload = [
                item.model_dump(mode="json") for item in memory.store.list_proposals()
            ]
        elif args.command == "memory-confirm":
            memory_payload = memory.confirm(args.proposal_id).model_dump(mode="json")
        elif args.command == "memory-reject":
            memory_payload = memory.store.reject_proposal(args.proposal_id).model_dump(mode="json")
        elif args.command == "memory-edit":
            memory_payload = memory.confirm(args.proposal_id, args.value).model_dump(mode="json")
        elif args.command == "memory-forget":
            memory_payload = memory.store.forget(args.memory_id).model_dump(mode="json")
        elif args.command == "memory-export":
            memory_payload = memory.store.export()
        else:
            memory_payload = memory.store.health().model_dump(mode="json")
        print(json.dumps(memory_payload, ensure_ascii=False, indent=2))
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
