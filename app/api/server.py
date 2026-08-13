"""最小 FastAPI（M3-A）：任务创建 / 查询 / 恢复 / 追踪 / providers。

- POST /tasks 默认 model_mode=fake，避免意外费用（005 十七）。
- 客户端不能传 base_url 或 API Key（schema 无此字段）。
- 客户端模型覆盖经服务端允许列表校验。
- 仅限本地单用户环境，不得暴露到公网（005 二十）。
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.config import AppSettings, load_settings
from app.core.resume import ResumePayload
from app.core.schemas import ClarificationPayload
from app.gateway.contracts import ProviderError
from app.memory.models import MemorySettings, MemoryType, PrivacyLevel
from app.memory.service import MemoryService
from app.runner import (
    _model_cost_available,
    approval_show,
    approvals_of,
    artifact_show,
    artifacts_of,
    diff_of,
    dry_run,
    evidence_list,
    evidence_show,
    list_tasks,
    provider_health,
    resume_task,
    rollback,
    run_task,
    status_task,
    tool_catalog,
    trace_task,
)
from app.security.permissions import (
    PermissionChangeError,
    PermissionMode,
    PermissionStore,
    RiskClass,
)
from app.usage.context import ContextPolicy
from app.usage.store import UsageStore
from app.voice.models import VoiceSettings

app = FastAPI(title="AI Team OS", version="0.3.0")


@app.middleware("http")
async def desktop_session_auth(request: Request, call_next):
    """Bind packaged API access to the current Tauri process, never to a static secret."""
    expected = os.environ.get("AI_TEAM_OS_DESKTOP_SESSION_TOKEN")
    origin = request.headers.get("origin", "")
    allowed_origins = {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"}
    if expected and request.method == "OPTIONS" and origin in allowed_origins:
        return JSONResponse(
            status_code=204,
            content=None,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Headers": "content-type,x-desktop-session",
                "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
                "Access-Control-Allow-Private-Network": "true",
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            },
        )
    presented = request.headers.get("x-desktop-session", "")
    if expected and not secrets.compare_digest(presented, expected):
        return JSONResponse(status_code=401, content={"detail": "desktop session required"})
    response = await call_next(request)
    if expected:
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
    return response

# 本地单用户开发模式：不实现用户认证，文档注明不可暴露公网（005 十七/二十）
_settings_cache: AppSettings | None = None
_computer_cache = None
_voice_cache = None


def _data_dir() -> Path:
    return Path(os.environ.get("AI_TEAM_OS_DATA_DIR", "data"))


def _settings() -> AppSettings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = load_settings()
    return _settings_cache


def _permission_store() -> PermissionStore:
    return PermissionStore(_data_dir())


def _usage_store() -> UsageStore:
    return UsageStore(_data_dir())


def _usage_view(*, run_id: str | None = None, task_id: str | None = None, days: int | None = 30):
    summary = _usage_store().summary(run_id=run_id, task_id=task_id, days=days)
    current = summary.get("current_context")
    current_tokens = current.get("context_tokens_after") if current else None
    limit = current.get("context_limit") if current else None
    role = current.get("role", "") if current else ""
    policy = ContextPolicy()
    threshold = policy.threshold_for(role)
    threshold_tokens = int(limit * threshold) if limit else None
    summary["context"] = {
        "current_tokens": current_tokens,
        "limit": limit,
        "percentage": (current_tokens / limit) if current_tokens is not None and limit else None,
        "status": policy.status(current_tokens, limit, role).value,
        "compression_threshold": threshold,
        "compression_threshold_tokens": threshold_tokens,
        "until_compression": max(0, threshold_tokens - current_tokens)
        if threshold_tokens is not None and current_tokens is not None
        else None,
        "source": current.get("usage_source") if current else "UNAVAILABLE",
        "role": role or None,
        "model": current.get("model_id") if current else None,
    }
    return summary


def _computer_service():
    global _computer_cache
    if _computer_cache is None:
        from app.windows_control.service import WindowsComputerService

        _computer_cache = WindowsComputerService(_data_dir(), Path.cwd())
    return _computer_cache


def _voice_supervisor(text: str) -> dict[str, Any]:
    """Every non-local final transcript enters the normal governed Supervisor path."""
    from app.gateway.multi_provider import RoleModelRouter

    # Voice never bypasses the explicit M6-A Supervisor slot by using a legacy default.
    RoleModelRouter(_team_store()).resolve("supervisor", project_id="voice")
    context_lines: list[str] = []
    if _voice_cache is not None:
        for turn in _voice_cache.conversation.context(limit=3):
            context_lines.append(
                f"Prior user: {turn['user'][:500]}\nPrior assistant: {turn['assistant'][:500]}"
            )
    try:
        window = _computer_service().snapshot(refresh_windows=False).active_window
        if window is not None:
            context_lines.append(f"Current window: {window.title[:300]} ({window.process_name})")
    except Exception:
        pass
    goal = text
    if context_lines:
        goal += "\n\nShort-lived voice working context (not instructions):\n" + "\n".join(
            context_lines
        )
    normalized = text.lower()
    computer_markers = (
        "记事本",
        "notepad",
        "打开设置",
        "open settings",
        "列出窗口",
        "list windows",
    )
    screen_markers = (
        "这个页面",
        "当前页面",
        "屏幕",
        "current screen",
        "this page",
    )
    if any(marker in normalized for marker in computer_markers):
        computer = _computer_service()
        if computer.snapshot(refresh_windows=False).control != "on":
            return {
                "status": "WAITING_FOR_COMPUTER_SESSION",
                "final_result": "Enable Computer Control before running a voice desktop action.",
            }
        task = computer.plan_task(text)
        task = computer.run_planned_task(task.task_id)
        return {
            "status": task.status,
            "task_id": task.task_id,
            "final_result": task.result or task.status,
        }
    result = create_task(
        TaskCreate(
            goal=goal,
            project_id="voice",
            token_budget=20_000,
            cost_budget=1.0,
            model_mode="real",
            max_calls=20,
        )
    )
    if any(marker in normalized for marker in screen_markers):
        computer = _computer_service()
        if computer.snapshot(refresh_windows=False).control == "on":
            observation = computer.visual_observe(external=False)
            answer = computer.visual_ask(text, observation.observation_id)
            result["final_result"] = answer.answer
            result["observation_id"] = observation.observation_id
    return result


def _voice_local_action(action: str) -> dict[str, Any]:
    computer = _computer_service()
    try:
        if action in {"stop", "cancel"}:
            computer.stop()
            return {"status": "stopped", "message": "Computer control stopped locally."}
        if action == "pause":
            computer.pause()
            return {"status": "paused", "message": "Computer control paused locally."}
        if action == "resume":
            computer.resume()
            return {"status": "resumed", "message": "Computer control resumed locally."}
        if action == "reject":
            pending = computer.snapshot(refresh_windows=False).pending_actions
            if not pending:
                return {"status": "nothing_to_reject", "message": "No approval is pending."}
            task = computer.reject(pending[0].approval_id)
            return {
                "status": "rejected",
                "message": "Pending computer action rejected locally.",
                "task_id": task.task_id,
            }
    except Exception as exc:  # local command still must not fall through to a model
        return {"status": "safe_noop", "message": str(getattr(exc, "code", "not_active"))}
    return {"status": "unsupported_local_action"}


def _voice_service():
    global _voice_cache
    if _voice_cache is None:
        from app.voice.service import VoiceService

        _voice_cache = VoiceService(
            _data_dir(), supervisor=_voice_supervisor, local_action=_voice_local_action
        )
    return _voice_cache


def _computer_error(exc: Exception) -> HTTPException:
    code = str(getattr(exc, "code", "computer_error"))
    status = (
        409
        if code
        in {
            "inactive_session",
            "expired_session",
            "paused_session",
            "action_after_stop",
            "approval_required",
            "invalid_task_state",
        }
        else 400
    )
    if code in {"task_not_found", "approval_not_found"}:
        status = 404
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


class TaskCreate(BaseModel):
    goal: str = Field(min_length=1)
    project_id: str = "default"
    token_budget: int = Field(default=10000, gt=0, le=1_000_000)
    cost_budget: float = Field(default=1.0, gt=0, le=100.0)
    model_mode: str = Field(default="fake", pattern="^(fake|real)$")
    max_calls: int = Field(default=30, gt=0, le=100)
    model_overrides: dict[str, str] = Field(default_factory=dict)
    # 006 十五：工具画像 / 项目别名 / 允许域名（客户端不能传绝对路径或动态 MCP）
    tool_profile: str = Field(default="readonly", pattern="^[a-z_]+$")
    project_alias: str | None = Field(default=None, max_length=100)
    allowed_domains: list[str] = Field(default_factory=list, max_length=20)

    model_config = {"extra": "forbid"}


class PermissionModeBody(BaseModel):
    mode: PermissionMode
    confirmed: bool = False
    user_explicit_action: bool


class PolicyExplainBody(BaseModel):
    action: str = Field(min_length=1, max_length=200)
    risk: RiskClass | None = None
    read_only: bool = False
    target: str = Field(default="", max_length=1000)
    task_explicit: bool = True


class TaskResume(BaseModel):
    clarification: str | None = None


class MemoryProposalBody(BaseModel):
    memory_type: MemoryType = Field(
        pattern="^(working|episodic|semantic_user|project|procedural_preference)$"
    )
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=1000)
    project_id: str | None = Field(default=None, max_length=200)
    privacy_level: PrivacyLevel = Field(
        default="personal", pattern="^(public|personal|sensitive|secret)$"
    )


class MemoryEditConfirmBody(BaseModel):
    value: str = Field(min_length=1, max_length=4000)


class PersonalizationControlBody(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    value: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    project_id: str | None = Field(default=None, max_length=200)
    task_type: str = Field(default="", max_length=100)


class PersonalizationSignalBody(BaseModel):
    signal_type: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)
    task_id: str = Field(min_length=1, max_length=200)
    project_id: str | None = Field(default=None, max_length=200)


class PersonalizationDecisionBody(BaseModel):
    decision: Literal["yes", "no", "project", "suppress"]
    project_id: str | None = Field(default=None, max_length=200)


def _memory() -> MemoryService:
    return MemoryService.from_data_dir(_data_dir())


def _adaptive():
    from app.personalization.service import AdaptiveService

    return AdaptiveService.from_data_dir(_data_dir())


def _memory_event(event_type: str, memory_id: str, run_id: str | None = None) -> None:
    from app.core.events import emit as event_emit
    from app.core.events import init as events_init

    events_init(_data_dir())
    event_emit(
        task_id=run_id or "memory-control",
        run_id=run_id or "memory-control",
        event_type=event_type,
        actor_type="user",
        actor_id="memory_center",
        summary=event_type.replace("_", " "),
        payload_safe={"memory_id": memory_id},
    )


@app.get("/memory")
def memories(
    project_id: str | None = None,
    status: str | None = None,
    memory_type: str | None = None,
    source_type: str | None = None,
) -> dict[str, Any]:
    service = _memory()
    records = service.store.list(
        project_id=project_id,
        status=status,
        memory_type=memory_type,
        source_type=source_type,
        include_global=project_id is not None,
    )
    health = service.store.health()
    return {
        "memories": [record.model_dump(mode="json") for record in records],
        "metrics": health.model_dump(mode="json"),
    }


@app.get("/memory/search")
def memory_search(
    q: str = "",
    project_id: str | None = None,
    status: str | None = None,
    memory_type: str | None = None,
    source_type: str | None = None,
) -> dict[str, Any]:
    records = _memory().store.search(
        q,
        project_id=project_id,
        status=status,
        memory_type=memory_type,
        source_type=source_type,
    )
    return {"memories": [record.model_dump(mode="json") for record in records]}


@app.get("/memory/proposals")
def memory_proposals(project_id: str | None = None) -> dict[str, Any]:
    proposals = _memory().store.list_proposals(project_id=project_id)
    return {"proposals": [item.model_dump(mode="json") for item in proposals]}


@app.post("/memory/proposals")
def create_memory_proposal(body: MemoryProposalBody) -> dict[str, Any]:
    proposal, decision = _memory().propose(
        memory_type=body.memory_type,
        subject=body.subject,
        predicate=body.predicate,
        value=body.value,
        reason=body.reason,
        source_type="explicit_user_statement",
        source_ref="memory-center",
        project_id=body.project_id,
        privacy_level=body.privacy_level,
        trusted_user_source=True,
    )
    if proposal is None:
        raise HTTPException(status_code=400, detail=decision.reason)
    _memory_event("memory_proposed", proposal.proposal_id)
    return proposal.model_dump(mode="json")


@app.post("/memory/proposals/{proposal_id}/confirm")
def confirm_memory_proposal(proposal_id: str) -> dict[str, Any]:
    try:
        record = _memory().confirm(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="memory proposal not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _memory_event("memory_confirmed", record.memory_id, record.source_ref)
    return record.model_dump(mode="json")


@app.post("/memory/proposals/{proposal_id}/reject")
def reject_memory_proposal(proposal_id: str) -> dict[str, Any]:
    try:
        proposal = _memory().store.reject_proposal(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="memory proposal not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _memory_event("memory_rejected", proposal.proposal_id, proposal.source_ref)
    return proposal.model_dump(mode="json")


@app.post("/memory/proposals/{proposal_id}/edit-confirm")
def edit_confirm_memory_proposal(proposal_id: str, body: MemoryEditConfirmBody) -> dict[str, Any]:
    try:
        record = _memory().confirm(proposal_id, body.value)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="memory proposal not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _memory_event("memory_confirmed", record.memory_id, record.source_ref)
    return record.model_dump(mode="json")


@app.get("/settings/memory")
@app.get("/memory/settings")
def memory_settings() -> dict[str, Any]:
    return _memory().store.get_settings().model_dump(mode="json")


@app.put("/settings/memory")
@app.put("/memory/settings")
def save_memory_settings(body: MemorySettings) -> dict[str, Any]:
    return _memory().store.set_settings(body).model_dump(mode="json")


@app.post("/memory/export")
def export_memory() -> dict[str, Any]:
    return _memory().store.export()


@app.delete("/memory")
def forget_all_memory() -> dict[str, Any]:
    service = _memory()
    count = 0
    for record in service.store.list(limit=10_000):
        if record.status not in {"forgotten", "expired"}:
            service.store.forget(record.memory_id)
            count += 1
    return {"forgotten": count}


@app.get("/memory/{memory_id}")
def memory_detail(memory_id: str) -> dict[str, Any]:
    record = _memory().store.get(memory_id)
    if record is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return record.model_dump(mode="json")


@app.delete("/memory/{memory_id}")
def forget_memory(memory_id: str) -> dict[str, Any]:
    try:
        record = _memory().store.forget(memory_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="memory not found") from exc
    _memory_event("memory_forgotten", record.memory_id, record.source_ref)
    return record.model_dump(mode="json")


@app.get("/tasks/{run_id}/memory")
def task_memory(run_id: str) -> dict[str, Any]:
    try:
        status_task(run_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run_id": run_id, "usage": _memory().store.usage_for_run(run_id)}


@app.get("/personalization")
def personalization_profile(
    project_id: str | None = None,
    task_type: str = "general",
    goal: str = "",
) -> dict[str, Any]:
    service = _adaptive()
    profile = service.derive(goal=goal, project_id=project_id, task_type=task_type)
    proposals = [
        item
        for item in service.memory.store.list_proposals(status="proposed", project_id=project_id)
        if "interaction_preference" in item.tags
    ]
    return {
        "profile": profile.model_dump(mode="json"),
        "proposals": [item.model_dump(mode="json") for item in proposals],
    }


@app.put("/personalization/control")
def personalization_control(body: PersonalizationControlBody) -> dict[str, Any]:
    from app.personalization.service import DEFAULTS

    if body.field not in DEFAULTS:
        raise HTTPException(status_code=400, detail="unsupported personalization field")
    service = _adaptive()
    service.store.set_control(
        field=body.field,
        value=body.value,
        enabled=body.enabled,
        project_id=body.project_id,
        task_type=body.task_type,
    )
    return service.derive(
        project_id=body.project_id, task_type=body.task_type or "general"
    ).model_dump(mode="json")


@app.delete("/personalization/reset")
def reset_personalization(
    project_id: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    removed = _adaptive().store.reset("local-user", project_id=project_id, field=field)
    return {"reset": removed, "project_id": project_id, "field": field}


@app.post("/personalization/signals")
def personalization_signal(body: PersonalizationSignalBody) -> dict[str, Any]:
    try:
        proposal = _adaptive().observe(
            signal_type=body.signal_type,
            value=body.value,
            task_id=body.task_id,
            project_id=body.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"proposal": proposal.model_dump(mode="json") if proposal is not None else None}


@app.post("/personalization/proposals/{proposal_id}/decision")
def personalization_decision(proposal_id: str, body: PersonalizationDecisionBody) -> dict[str, Any]:
    service = _adaptive()
    proposal = service.memory.store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="personalization proposal not found")
    if body.decision == "yes":
        return service.memory.confirm(proposal_id).model_dump(mode="json")
    if body.decision == "project":
        if not body.project_id:
            raise HTTPException(status_code=400, detail="project decision requires project_id")
        service.memory.store.reject_proposal(proposal_id)
        replacement, decision = service.memory.propose(
            memory_type="procedural_preference",
            subject=proposal.subject,
            predicate=proposal.predicate,
            value=proposal.proposed_value,
            reason=proposal.reason,
            source_type="user_confirmation",
            source_ref=proposal.proposal_id,
            project_id=body.project_id,
            confidence=proposal.confidence,
            privacy_level="personal",
            tags=["interaction_preference"],
            trusted_user_source=True,
        )
        if replacement is None:
            raise HTTPException(status_code=409, detail=decision.reason)
        return service.memory.confirm(replacement.proposal_id).model_dump(mode="json")
    service.memory.store.reject_proposal(proposal_id)
    service.store.reject_proposal(
        proposal.subject,
        proposal.project_id,
        forever=body.decision == "suppress",
    )
    return {
        "proposal_id": proposal_id,
        "status": "rejected",
        "suppressed": body.decision == "suppress",
    }


@app.get("/providers")
def providers() -> dict[str, Any]:
    s = _settings()
    return {
        "provider": s.model.provider,
        "real_enabled": s.model.enable_real,
        "default_model": s.model.default_model,
        "role_routing": s.routing.role_defaults,
        "allowed_models": s.routing.allowed_models,
        "fallback_models": s.routing.fallback_models,
        "note": "API Key 不在此响应中",
    }


@app.get("/providers/health")
def health() -> dict[str, Any]:
    return provider_health(_settings())


@app.get("/tools")
def tools() -> dict[str, Any]:
    """006 十五：只读工具目录。"""
    return {"tools": tool_catalog(_settings())}


@app.get("/tools/{name}")
def tool_info(name: str) -> dict[str, Any]:
    """006 十五：单个工具信息。"""
    entry = next((t for t in tool_catalog(_settings()) if t["name"] == name), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown tool: {name}")
    return entry


@app.get("/settings/security/permission-mode")
def get_permission_mode() -> dict[str, Any]:
    setting = _permission_store().get()
    return {
        **setting.model_dump(mode="json"),
        "first_upgrade_notice": not setting.changed_by_user,
    }


@app.put("/settings/security/permission-mode")
def put_permission_mode(body: PermissionModeBody) -> dict[str, Any]:
    try:
        setting, old = _permission_store().set_mode(
            body.mode,
            changed_by_user=body.user_explicit_action,
            confirmed=body.confirmed,
        )
    except PermissionChangeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from app.core.events import emit as event_emit
    from app.core.events import init as events_init

    events_init(_data_dir())
    event_emit(
        task_id="settings",
        run_id="settings",
        event_type="permission_mode_changed",
        actor_type="user",
        actor_id="local-user",
        summary=f"permission mode changed from {old.value} to {setting.mode.value}",
        payload_safe={"old": old.value, "new": setting.mode.value, "timestamp": setting.changed_at},
    )
    for task in list_tasks(_data_dir()):
        if task.get("status") not in {"running", "paused"}:
            continue
        event_emit(
            task_id=str(task["task_id"]),
            run_id=str(task["run_id"]),
            event_type="permission_mode_changed",
            actor_type="user",
            actor_id="local-user",
            summary=f"live permission changed from {old.value} to {setting.mode.value}",
            payload_safe={
                "old": old.value,
                "new": setting.mode.value,
                "timestamp": setting.changed_at,
            },
        )
    return setting.model_dump(mode="json")


@app.post("/security/policy/explain")
def explain_permission_policy(body: PolicyExplainBody) -> dict[str, Any]:
    return (
        _permission_store()
        .explain(
            action=body.action,
            risk=body.risk,
            read_only=body.read_only,
            target=body.target,
            task_explicit=body.task_explicit,
        )
        .model_dump(mode="json")
    )


@app.get("/security/permission-history")
def permission_history(limit: int = 50) -> dict[str, Any]:
    return {"actions": [item.model_dump(mode="json") for item in _permission_store().recent(limit)]}


@app.get("/tasks/{run_id}/evidence")
def task_evidence(run_id: str) -> dict[str, Any]:
    """006 十五：任务 Evidence 摘要。"""
    try:
        return evidence_list(run_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/evidence/{evidence_id}")
def evidence_detail(evidence_id: str) -> dict[str, Any]:
    """006 十五：Evidence 原始快照（已脱敏）。"""
    try:
        return evidence_show(evidence_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/tasks")
def create_task(body: TaskCreate) -> dict[str, Any]:
    overrides = dict(body.model_overrides)
    if body.project_alias:
        overrides["project_alias"] = body.project_alias
    if body.allowed_domains:
        overrides["allowed_domains"] = ";".join(body.allowed_domains)
    try:
        report = run_task(
            body.goal,
            token_budget=body.token_budget,
            cost_budget=body.cost_budget,
            project_id=body.project_id,
            data_dir=_data_dir(),
            model_mode=body.model_mode,
            model_overrides=overrides or None,
            settings=_settings(),
            max_model_calls=body.max_calls,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=exc.safe_message) from exc
    except ValueError as exc:
        # 模型覆盖白名单失败等配置错误 → 400（005 17：API 错误使用安全消息）
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "task_id": report.task_id,
        "run_id": report.run_id,
        "status": report.status,
        "permission_mode": report.state.permission_mode,
        "permission_mode_at_start": report.state.permission_mode_at_start,
        "final_result": report.state.final_result,
        "usage": report.usage,
        "call_count": report.call_count,
        "tool_call_count": report.tool_call_count,
        "memory_context_count": len(report.state.memory_refs),
        "personalization_applied_count": len(report.state.personalization_applied),
    }


def _task_model_identity(state) -> dict[str, Any]:
    if state.model_mode != "real":
        return {
            "badge": "DEMO",
            "provider": "Fake Model",
            "default_model": "deterministic-fake",
            "role_models": {
                role: "deterministic-fake"
                for role in ("supervisor", "planner", "researcher", "executor", "reviewer")
            },
        }
    provider = _provider_store().default()
    if provider is None:
        return {"badge": "REAL", "provider": "Unconfigured", "default_model": "", "role_models": {}}
    return {
        "badge": "REAL",
        "provider": provider.provider_name,
        "default_model": provider.default_model,
        "role_models": provider.role_models,
    }


@app.get("/tasks/{run_id}")
def get_task(run_id: str) -> dict[str, Any]:
    try:
        report = status_task(run_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    state = report.state
    return {
        "task_id": report.task_id,
        "run_id": report.run_id,
        "status": report.status,
        "current_status": state.current_status,
        "failure_code": state.failure_code,
        "model_mode": state.model_mode,
        "permission_mode": state.permission_mode,
        "permission_mode_at_start": state.permission_mode_at_start,
        "permission_mode_current": _permission_store().mode().value,
        "goal": state.user_goal,
        "clarified_goal": state.clarified_goal,
        "pending_clarification_id": state.pending_clarification_id,
        "final_result": state.final_result,
        "plan": state.plan,
        "subtasks": [
            {
                "subtask_id": s.subtask_id,
                "title": s.title,
                "role": s.assigned_role,
                "status": s.runtime_status,
                "rework_count": s.rework_count,
                "dependencies": list(s.dependencies),
                "token_budget": s.token_budget,
                "tool_call_budget": s.tool_call_budget,
                "evidence_refs": list(s.evidence_refs or []),
            }
            for s in state.subtasks
        ],
        "token_budget": state.token_budget,
        "cost_budget": state.cost_budget,
        "max_model_calls": state.max_model_calls,
        "budget_usage": state.budget_usage,
        "cost_available": _model_cost_available(
            _data_dir(), state.model_mode, state.task_id, report.run_id or state.task_id
        ),
        "rework_count": state.rework_count,
        "usage": report.usage,
        "tool_call_count": report.tool_call_count,
        "memory_context_count": len(state.memory_refs),
        "personalization_applied_count": len(state.personalization_applied),
        "personalization_applied": state.personalization_applied,
        "model_identity": _task_model_identity(state),
    }


@app.post("/tasks/{run_id}/resume")
def resume(run_id: str, body: TaskResume | None = None) -> dict[str, Any]:
    body = body or TaskResume()
    try:
        snapshot = status_task(run_id, data_dir=_data_dir())
        if body.clarification:
            pending_id = snapshot.state.pending_clarification_id
            if not pending_id:
                raise HTTPException(status_code=409, detail="run 不在澄清挂起状态")
            payload: ResumePayload | ClarificationPayload = ClarificationPayload(
                clarification_id=pending_id, answer=body.clarification
            )
        else:
            payload = ResumePayload(action="continue")
        report = resume_task(run_id, payload=payload, data_dir=_data_dir(), settings=_settings())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "task_id": report.task_id,
        "run_id": report.run_id,
        "status": report.status,
        "final_result": report.state.final_result,
        "usage": report.usage,
        "tool_call_count": report.tool_call_count,
    }


@app.get("/tasks/{run_id}/trace")
def trace(run_id: str) -> dict[str, Any]:
    try:
        return trace_task(run_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/tasks/{run_id}/dry-run")
def task_dry_run(run_id: str) -> dict[str, Any]:
    """基于已保存任务的 dry-run（不真正调用）。"""
    try:
        report = status_task(run_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dry_run(
        report.state.user_goal, report.state.token_budget, report.state.cost_budget, _settings()
    )


# ================= 007 十七：审批 / Artifact / Diff / 回滚 =================


class ApprovalDecisionBody(BaseModel):
    """批准/拒绝只提交 approval_id（路径）与可选说明；其余参数不能由客户端修改。"""

    reason: str | None = Field(default=None, max_length=500)


class RollbackBody(BaseModel):
    """回滚请求：目标 Patch 的 approval_id + 可选已批准的回滚审批 approval_id。"""

    patch_approval_id: str = Field(min_length=1, max_length=64)
    approval_id: str | None = Field(default=None, min_length=1, max_length=64)


def _decide_pending_approval(
    approval_id: str, decision: Literal["approved", "rejected"], reason: str | None
) -> tuple[dict[str, Any], Any]:
    """Decide the graph's pending approval exactly once, then resume its run."""
    from app.core.approval import ApprovalError, ApprovalService
    from app.core.schemas import ApprovalPayload

    data_dir = _data_dir()
    record = approval_show(approval_id, data_dir=data_dir)
    run_id = record.get("run_id") or record["task_id"]
    snapshot = status_task(run_id, data_dir=data_dir)
    if snapshot.state.current_status == "paused":
        try:
            report = resume_task(
                run_id,
                payload=ApprovalPayload(
                    approval_id=approval_id,
                    decision=decision,
                    reason=reason,
                ),
                data_dir=data_dir,
            )
        except (RuntimeError, ApprovalError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return record, report

    # Supplemental approvals can outlive a completed run. Preserve the existing
    # decision-on-record behavior, but report that the graph cannot be resumed.
    approval = ApprovalService(
        storage_path=data_dir / "runtime" / "workspaces" / record["task_id"] / "approvals.jsonl"
    )
    try:
        approval.decide(approval_id, decision, reason)
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(
        status_code=409,
        detail=f"run {run_id} is not paused (current_status={snapshot.state.current_status!r})",
    )


@app.get("/tasks/{run_id}/approvals")
def task_approvals(run_id: str) -> list[dict[str, Any]]:
    try:
        return approvals_of(run_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/approvals/{approval_id}")
def get_approval(approval_id: str) -> dict[str, Any]:
    try:
        return approval_show(approval_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, body: ApprovalDecisionBody | None = None) -> dict[str, Any]:
    """批准（幂等）：定位任务 → 决策落盘 → 恢复。已拒绝/过期返回 409。"""
    _record, report = _decide_pending_approval(
        approval_id, "approved", body.reason if body else None
    )
    return {
        "approval_id": approval_id,
        "status": "approved",
        "task_status": report.state.current_status,
    }


@app.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, body: ApprovalDecisionBody | None = None) -> dict[str, Any]:
    """拒绝：不应用补丁，任务标记未实施（GT-W03）。"""
    _record, report = _decide_pending_approval(
        approval_id, "rejected", body.reason if body else None
    )
    return {
        "approval_id": approval_id,
        "status": "rejected",
        "task_status": report.state.current_status,
    }


@app.get("/tasks/{run_id}/artifacts")
def task_artifacts(run_id: str) -> list[dict[str, Any]]:
    try:
        return artifacts_of(run_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> dict[str, Any]:
    try:
        return artifact_show(artifact_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/tasks/{run_id}/diff")
def task_diff(run_id: str) -> dict[str, Any]:
    try:
        return diff_of(run_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/tasks/{run_id}/rollback")
def task_rollback(run_id: str, body: RollbackBody) -> dict[str, Any]:
    """回滚指定 Patch（须已批准的回滚审批；操作哈希不匹配返回 409）。"""
    from app.core.rollback import RollbackError

    try:
        return rollback(run_id, body.patch_approval_id, body.approval_id, data_dir=_data_dir())
    except (KeyError, RollbackError) as exc:
        status = 404 if isinstance(exc, KeyError) else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# ============ UI-01（010 第四十一部分）：Dashboard / Tasks / Agents / Health / SSE ============


@app.get("/dashboard")
def dashboard() -> dict[str, Any]:
    """Dashboard 聚合（健康/指标/最近任务/Agent 团队）。"""
    from app.runner import dashboard_data

    return dashboard_data(data_dir=_data_dir())


@app.get("/tasks")
def tasks_list() -> list[dict[str, Any]]:
    """任务列表（checkpoints.db 各 thread 最新状态）。"""
    from app.runner import list_tasks

    return list_tasks(data_dir=_data_dir())


class UsageRetentionBody(BaseModel):
    retention: Literal["7", "30", "90", "forever"]


@app.get("/usage")
def usage(days: int = 30, task_id: str | None = None, run_id: str | None = None):
    if days not in {1, 7, 30, 90}:
        raise HTTPException(status_code=400, detail="days must be 1, 7, 30, or 90")
    return _usage_view(run_id=run_id, task_id=task_id, days=days)


@app.get("/tasks/{run_id}/usage")
def task_usage(run_id: str):
    return _usage_view(run_id=run_id, days=None)


@app.get("/usage/active-context")
def active_context():
    active = next(
        (
            task
            for task in list_tasks(_data_dir())
            if task.get("status") not in {"completed", "failed", "cancelled"}
        ),
        None,
    )
    if not active:
        return {"active": False, "context": None}
    return {
        "active": True,
        "run_id": active["run_id"],
        "context": _usage_view(run_id=active["run_id"], days=None)["context"],
    }


@app.get("/settings/usage")
def usage_settings():
    days = _usage_store().retention_days()
    return {"retention": "forever" if days is None else str(days)}


@app.put("/settings/usage")
def update_usage_settings(body: UsageRetentionBody):
    value = None if body.retention == "forever" else int(body.retention)
    _usage_store().set_retention(value)
    return {"retention": body.retention}


@app.get("/agents")
def agents() -> list[dict[str, Any]]:
    """Agent 目录（010 第二十二部分，本阶段只读）。"""
    from app.core.registry import default_registry
    from app.runner import list_tasks

    registry = default_registry()
    active_task = None
    waiting_task = None
    for task in list_tasks(_data_dir()):
        if active_task is None and task.get("status") in {"running", "paused"}:
            active_task = task
        if task.get("status") != "paused":
            continue
        if any(a.get("status") == "pending" for a in approvals_of(task["run_id"], _data_dir())):
            waiting_task = task
            break
    if waiting_task is not None:
        active_task = waiting_task
    active_subtask = None
    latest_completed = None
    if active_task is not None:
        report = status_task(active_task["run_id"], data_dir=_data_dir())
        active_subtask = next(
            (s for s in reversed(report.state.subtasks) if s.runtime_status != "passed"),
            None,
        )
        latest_completed = next(
            (s for s in reversed(report.state.subtasks) if s.runtime_status == "passed"),
            None,
        )
    out = []
    active_identity = None
    if active_task is not None:
        active_identity = _task_model_identity(report.state)
    for agent in registry.all():
        waiting = bool(waiting_task and agent.role_type == "executor")
        assigned = bool(active_subtask and active_subtask.assigned_role == agent.role_type)
        supervising = bool(active_task and agent.role_type == "supervisor")
        out.append(
            {
                "agent_id": agent.agent_id,
                "role": agent.role_type,
                "display_name": agent.display_name,
                "model": (
                    active_identity.get("role_models", {}).get(agent.role_type)
                    or active_identity.get("default_model")
                    if active_identity
                    else agent.model_scenario
                ),
                "provider": active_identity.get("provider") if active_identity else "Fake Model",
                "model_mode": report.state.model_mode if active_task is not None else "fake",
                "enabled": agent.enabled,
                "token_limit": agent.token_limit,
                "max_tool_calls": agent.max_tool_calls,
                "allowed_tools": sorted(agent.allowed_tools),
                "status": (
                    "waiting_approval"
                    if waiting
                    else ("thinking" if assigned or supervising else "idle")
                ),
                "current_task": (
                    waiting_task["goal"] if waiting_task is not None and waiting else None
                ),
                "last_action": "approval requested" if waiting else None,
                "current_action": (
                    "approval_requested"
                    if waiting
                    else (
                        "coordinating"
                        if supervising
                        else ("working_on_subtask" if assigned else None)
                    )
                ),
                "current_subtask": (
                    active_subtask.title if (assigned or supervising) and active_subtask else None
                ),
                "latest_completed": (
                    latest_completed.title if latest_completed is not None else None
                ),
            }
        )
    return out


@app.get("/system/health")
def system_health() -> dict[str, str]:
    """系统健康（010 第七部分 System Health）。"""
    from app.runner import _system_health

    return _system_health(_data_dir())


@app.get("/settings/status")
def settings_status() -> dict[str, Any]:
    """安全配置状态（010 第二十五部分；绝不显示 Secret 值）。"""
    from app.core.config import allowed_read_roots

    settings = _settings()
    # 005 7.4：real 模式显式开启 = env 开关 或 网页已保存 openai_compatible 凭据
    web_key = _secret_resolver().resolve("openai_compatible.api_key") or ""
    real_effective = getattr(settings.model, "enable_real", False) or bool(web_key)
    return {
        "model_provider": {
            "name": "openai_compatible",
            "status": "Configured" if real_effective else "Missing",
            "base_url_configured": bool(
                getattr(settings.model, "base_url", None)
                or _secret_resolver().resolve("openai_compatible.base_url")
            ),
            "api_key_configured": bool(getattr(settings.model, "api_key", None) or web_key),
        },
        "github": {
            "status": "Configured" if os.environ.get("AI_TEAM_GITHUB_TOKEN") else "Missing",
            "token_configured": bool(os.environ.get("AI_TEAM_GITHUB_TOKEN")),
        },
        "real_model": {"status": "Enabled" if real_effective else "Disabled"},
        "allowed_read_roots": {"count": len(allowed_read_roots())},
        "mcp": {"servers": 0, "status": "Disabled"},
        "network_isolation": "Best Effort",
        "sandbox": {"status": "Online" if allowed_read_roots() else "Disabled"},
    }


def _format_sse_frame(sequence: int, data: dict) -> str:
    """SSE 帧：默认 message 事件（无 event: 行）→ 客户端 message 监听直接接收。"""
    import json as _json

    return f"id: {sequence}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/tasks/{run_id}/events")
def task_events(run_id: str, after: int = 0) -> Any:
    """SSE 实时事件（010 第十四部分）：`after` 支持 replay（客户端 ?after=<seq>）。

    默认 message 事件（无 event: 行）→ 客户端 message 监听直接接收；
    keepalive 用 time.sleep 节流（sync generator 中 asyncio.sleep 无效）。
    """
    from fastapi.responses import StreamingResponse

    from app.core.events import get_store

    store = get_store()
    if store is None:
        from app.core.events import init as events_init

        events_init(_data_dir())
        store = get_store()
    # 校验 run 存在
    try:
        task_report = status_task(run_id, data_dir=_data_dir())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")

    def _stream():
        import time

        last = max(after, 0)
        idle = 0
        while True:
            events = store.list_events(run_id=run_id, after_sequence=last)
            # Older role calls that omitted request.run_id were safely stored
            # under task_id. Merge them for complete per-role UI telemetry.
            if task_report.task_id != run_id:
                events.extend(store.list_events(run_id=task_report.task_id, after_sequence=last))
                events.sort(key=lambda event: event.sequence)
            for ev in events:
                yield _format_sse_frame(ev.sequence, ev.model_dump())
                last = ev.sequence
                idle = 0
            if not events:
                idle += 1
                if idle >= 3:
                    # 任务终态后补发状态事件再结束（客户端据此关闭连接停止重连）
                    try:
                        st = status_task(run_id, data_dir=_data_dir())
                        if st.state.current_status in ("completed", "failed"):
                            from datetime import datetime, timezone

                            payload = {
                                "event_id": f"terminal-{run_id}-{last + 1}",
                                "event_type": "task_status_changed",
                                "task_id": task_report.task_id,
                                "run_id": run_id,
                                "sequence": last + 1,  # 虚拟序列：仅用于终态通知
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "summary": f"task {st.state.current_status}",
                                "actor_type": "system",
                                "actor_id": run_id,
                                "payload_safe": {"status": st.state.current_status},
                            }
                            yield _format_sse_frame(last + 1, payload)
                            return
                    except KeyError:
                        return
                yield ": keepalive\n\n"
            time.sleep(1.0)  # sync generator：asyncio.sleep 不会生效

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============ M5-A Computer Control（默认 OFF，所有动作经 WindowsActionGateway） ============


class ComputerStartBody(BaseModel):
    capability: Literal["observe_only", "low_risk_control", "ask_every_action"] = "observe_only"
    ttl_minutes: int = Field(default=15, ge=1, le=60)


class ComputerTaskBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)


class VisualObserveBody(BaseModel):
    scope: Literal["full_screen", "monitor", "active_window", "window", "region"] = "active_window"
    monitor_id: str | None = None
    window_id: str | None = None
    region: dict[str, int] | None = None
    external: bool = False


class VisualGroundBody(BaseModel):
    observation_id: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=500)


class ScreenQuestionBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    observation_id: str | None = Field(default=None, max_length=100)


class VisualActionBody(BaseModel):
    grounding_id: str = Field(min_length=1, max_length=100)
    approved: bool = False


class VisionSettingsBody(BaseModel):
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    allow_external_processing: bool = False
    consent_acknowledged: bool = False
    auto_refresh: bool = False


@app.get("/computer")
def computer_status() -> dict[str, Any]:
    return _computer_service().snapshot().model_dump(mode="json")


@app.post("/computer/session/start")
def computer_start(body: ComputerStartBody) -> dict[str, Any]:
    from app.windows_control.models import SessionCapability

    try:
        _computer_service().start_session(
            SessionCapability(body.capability), ttl_minutes=body.ttl_minutes
        )
        return _computer_service().snapshot().model_dump(mode="json")
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/session/pause")
def computer_pause() -> dict[str, Any]:
    try:
        _computer_service().pause()
        return _computer_service().snapshot(refresh_windows=False).model_dump(mode="json")
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/session/resume")
def computer_resume() -> dict[str, Any]:
    try:
        _computer_service().resume()
        return _computer_service().snapshot().model_dump(mode="json")
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/session/stop")
def computer_stop() -> dict[str, Any]:
    try:
        _computer_service().stop()
        return _computer_service().snapshot(refresh_windows=False).model_dump(mode="json")
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.get("/computer/screen")
def computer_screen() -> dict[str, Any]:
    try:
        return _computer_service().capture_screen().model_dump(mode="json")
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.get("/computer/windows/{window_id}/screen")
def computer_window_screen(window_id: str) -> dict[str, Any]:
    try:
        return _computer_service().capture_window(window_id).model_dump(mode="json")
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.get("/computer/windows/{window_id}/accessibility")
def computer_window_accessibility(window_id: str) -> dict[str, Any]:
    try:
        elements = _computer_service().accessibility_tree(window_id)
        return {"elements": [item.model_dump(mode="json") for item in elements]}
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.get("/computer/vision")
def computer_vision_status() -> dict[str, Any]:
    return _computer_service().visual.status()


@app.put("/computer/vision/settings")
def computer_vision_settings(body: VisionSettingsBody) -> dict[str, Any]:
    try:
        registry = _computer_service().visual.capabilities
        registry.configure_route(body.provider, body.model)
        registry.set_external_processing(
            body.allow_external_processing,
            consent_acknowledged=body.consent_acknowledged,
        )
        registry.settings.auto_refresh = body.auto_refresh
        return _computer_service().visual.status()
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/vision/observe")
def computer_visual_observe(body: VisualObserveBody) -> dict[str, Any]:
    from app.desktop_vision.models import CaptureScope
    from app.windows_control.models import Bounds

    try:
        region = Bounds(**body.region) if body.region else None
        observation = _computer_service().visual_observe(
            scope=CaptureScope(body.scope),
            monitor_id=body.monitor_id,
            window_id=body.window_id,
            region=region,
            external=body.external,
        )
        return observation.model_dump(mode="json")
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.get("/computer/vision/observations/{observation_id}/preview")
def computer_visual_preview(observation_id: str) -> dict[str, Any]:
    try:
        return _computer_service().visual.preview(observation_id)
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/vision/ground")
def computer_visual_ground(body: VisualGroundBody) -> dict[str, Any]:
    try:
        return (
            _computer_service()
            .visual_ground(body.observation_id, body.target)
            .model_dump(mode="json")
        )
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/vision/ask")
def computer_visual_ask(body: ScreenQuestionBody) -> dict[str, Any]:
    try:
        return (
            _computer_service()
            .visual_ask(body.question, body.observation_id)
            .model_dump(mode="json")
        )
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/vision/actions")
def computer_visual_action(body: VisualActionBody) -> dict[str, Any]:
    try:
        return (
            _computer_service()
            .visual_act(body.grounding_id, approved=body.approved)
            .model_dump(mode="json")
        )
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/tasks/plan")
def computer_plan(body: ComputerTaskBody) -> dict[str, Any]:
    try:
        return _computer_service().plan_task(body.goal).model_dump(mode="json")
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code.value, "message": "Real model could not create a safe plan"},
        ) from exc
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/tasks/{task_id}/run")
def computer_run(task_id: str) -> dict[str, Any]:
    try:
        return _computer_service().run_planned_task(task_id).model_dump(mode="json")
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code.value, "message": "Real Reviewer could not complete"},
        ) from exc
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/approvals/{approval_id}/approve")
def computer_approve(approval_id: str) -> dict[str, Any]:
    try:
        return _computer_service().approve(approval_id).model_dump(mode="json")
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code.value, "message": "Real Reviewer could not complete"},
        ) from exc
    except Exception as exc:
        raise _computer_error(exc) from exc


@app.post("/computer/approvals/{approval_id}/reject")
def computer_reject(approval_id: str) -> dict[str, Any]:
    try:
        return _computer_service().reject(approval_id).model_dump(mode="json")
    except Exception as exc:
        raise _computer_error(exc) from exc


# ============ Connections / Secret 管理（010 三十~三十六 / 009-A） ============


class ConnectionBody(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=2000)
    models: dict[str, str] | None = (
        None  # 角色 → 模型（default/supervisor/planner/researcher/executor/reviewer）
    )
    storage_mode: str = Field(default="session", pattern="^(session|secure)$")
    local_provider: bool = False  # 仅 Ollama 本地 Provider 允许 localhost（010 三十六）


class CustomProviderBody(BaseModel):
    provider_name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    models_endpoint: str = Field(default="/models", min_length=1, max_length=200)
    chat_endpoint: str = Field(default="/chat/completions", min_length=1, max_length=200)
    api_mode: str = Field(default="openai_compatible", pattern="^openai_compatible$")
    default_model: str = Field(default="", max_length=200)
    role_models: dict[str, str] = Field(default_factory=dict)
    is_default: bool = False
    local_provider: bool = False
    test_provider: bool = False
    context_window: int | None = Field(default=None, gt=0, le=10_000_000)


class CustomCredentialBody(BaseModel):
    api_key: str = Field(min_length=1, max_length=2000)
    storage_mode: str = Field(default="session", pattern="^(session|secure)$")


class CustomModelTestBody(BaseModel):
    model: str | None = Field(default=None, max_length=200)


_resolver = None  # 惰性初始化（依赖 data_dir）
_CONNECTION_PROVIDERS = (
    "openai_compatible",
    "github",
    "ollama",
    "test_provider",
    "github_test",
)
_CONNECTION_HEALTH: dict[str, str] = {}


def _provider_store():
    from app.core.provider_store import ProviderStore

    return ProviderStore(_data_dir() / "runtime" / "providers.sqlite")


def _custom_provider_info(provider) -> dict[str, Any]:
    store = _provider_store()
    secret_key = store.secret_key(provider.provider_id)
    payload = provider.model_dump(mode="json", exclude={"configured", "storage"})
    payload["configured"] = _secret_resolver().resolve(secret_key) is not None
    payload["storage"] = _secret_resolver().store_mode(secret_key)
    payload["model_discovery_status"] = payload.pop("discovery_status")
    payload["model_count"] = len(provider.discovered_models)
    payload["context_window_source"] = "USER_CONFIGURED" if provider.context_window else None
    if provider.context_window and provider.default_model:
        from app.usage.models import CapabilitySource, ModelCapability

        _usage_store().set_capability(
            ModelCapability(
                provider_id=provider.provider_id,
                model_id=provider.default_model,
                context_window=provider.context_window,
                usage_reporting=True,
                source=CapabilitySource.USER_CONFIGURED,
            )
        )
    return payload


def _secret_resolver():
    global _resolver
    if _resolver is None:
        from app.core.secret_store import process_resolver

        _resolver = process_resolver(_data_dir())
    return _resolver


def _provider_info(provider: str) -> dict[str, Any]:
    """Provider 状态（绝不包含 Secret 值/片段）。"""

    resolver = _secret_resolver()
    base = _BASE_URLS.get(provider, "")
    models = _MODEL_ROLES.get(provider, {})
    if provider == "ollama":
        configured = True  # 本地 Provider 无需密钥
        storage = "local_provider"
        base = base or "http://127.0.0.1:11434"
    else:
        configured = resolver.resolve(provider_key(provider)) is not None
        storage = resolver.store_mode(provider_key(provider))
    return {
        "provider": provider,
        "configured": configured,
        "base_url": base,
        "models": models,
        "storage": storage,
        "health": _CONNECTION_HEALTH.get(provider, "configured" if configured else "missing"),
        "local_provider": provider == "ollama",
        "test_provider": provider in ("test_provider", "github_test"),
    }


_BASE_URLS = {
    "openai_compatible": "",
    "github": "https://api.github.com",
    "ollama": "http://127.0.0.1:11434",
    "test_provider": "https://test-provider.invalid/v1",
    "github_test": "https://github-test.invalid",
}

_MODEL_ROLES: dict[str, dict[str, str]] = {
    "openai_compatible": {},
    "github": {},
    "ollama": {},
    "test_provider": {},
    "github_test": {},
}


def provider_key(provider: str) -> str:
    if provider == "github":
        return "github.token"
    if provider == "github_test":
        return "github_test.token"
    return f"{provider}.api_key"


@app.get("/settings/connections")
def connections_status() -> dict[str, Any]:
    """Connections 状态（009-A 八；禁止返回任何 Secret）。"""
    return {p: _provider_info(p) for p in _CONNECTION_PROVIDERS}


@app.get("/settings/connections/providers")
def custom_providers() -> dict[str, Any]:
    return {"providers": [_custom_provider_info(item) for item in _provider_store().list()]}


@app.post("/settings/connections/providers")
def create_custom_provider(body: CustomProviderBody) -> dict[str, Any]:
    if body.test_provider:
        if body.base_url != "https://third-party-test.invalid/v1":
            raise HTTPException(status_code=400, detail="invalid isolated test provider URL")
    else:
        _validate_base_url("custom", body.base_url, local_ok=body.local_provider)
    try:
        provider = _provider_store().create(**body.model_dump())
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise HTTPException(status_code=409, detail="provider name already exists") from exc
        raise
    return _custom_provider_info(provider)


@app.get("/settings/connections/providers/{provider_id}")
def custom_provider(provider_id: str) -> dict[str, Any]:
    provider = _provider_store().get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="custom provider not found")
    return _custom_provider_info(provider)


@app.put("/settings/connections/providers/{provider_id}")
def update_custom_provider(provider_id: str, body: CustomProviderBody) -> dict[str, Any]:
    if body.test_provider:
        if body.base_url != "https://third-party-test.invalid/v1":
            raise HTTPException(status_code=400, detail="invalid isolated test provider URL")
    else:
        _validate_base_url("custom", body.base_url, local_ok=body.local_provider)
    try:
        provider = _provider_store().update(provider_id, **body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="custom provider not found") from exc
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise HTTPException(status_code=409, detail="provider name already exists") from exc
        raise
    return _custom_provider_info(provider)


@app.delete("/settings/connections/providers/{provider_id}")
def delete_custom_provider(provider_id: str) -> dict[str, Any]:
    store = _provider_store()
    try:
        store.delete(provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="custom provider not found") from exc
    _secret_resolver().delete(store.secret_key(provider_id))
    return {"provider_id": provider_id, "deleted": True}


@app.put("/settings/connections/providers/{provider_id}/credential")
def save_custom_credential(provider_id: str, body: CustomCredentialBody) -> dict[str, Any]:
    store = _provider_store()
    if store.get(provider_id) is None:
        raise HTTPException(status_code=404, detail="custom provider not found")
    try:
        storage = _secret_resolver().set(
            store.secret_key(provider_id), body.api_key, body.storage_mode
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"provider_id": provider_id, "configured": True, "storage": storage}


@app.delete("/settings/connections/providers/{provider_id}/credential")
def delete_custom_credential(provider_id: str) -> dict[str, Any]:
    store = _provider_store()
    if store.get(provider_id) is None:
        raise HTTPException(status_code=404, detail="custom provider not found")
    _secret_resolver().delete(store.secret_key(provider_id))
    return {"provider_id": provider_id, "configured": False, "storage": "missing"}


def _discover_custom_models(provider_id: str) -> dict[str, Any]:
    import time

    from app.core.provider_store import models_url, normalize_models
    from app.memory.models import utc_now

    started = time.perf_counter()
    store = _provider_store()
    provider = store.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="custom provider not found")
    if provider.test_provider:
        models = normalize_models(
            {
                "data": [
                    {"id": "m4-test-small", "owned_by": "isolated-test"},
                    {"id": "m4-test-pro", "owned_by": "isolated-test"},
                    {"id": "m4-test-reasoning", "owned_by": "isolated-test"},
                ]
            }
        )
        provider = store.update_discovery(provider_id, models, "success")
        return {
            "provider_id": provider_id,
            "status": "success",
            "models": [dict(item, display_name=item["id"]) for item in models],
            "count": len(models),
            "last_model_sync_at": provider.last_model_sync_at,
            "http_status": 200,
            "latency_ms": max(1, round((time.perf_counter() - started) * 1000)),
        }
    key = _secret_resolver().resolve(store.secret_key(provider_id))
    if not key:
        raise HTTPException(status_code=409, detail="credential is not configured")
    url = models_url(provider.base_url, provider.models_endpoint)
    _validate_base_url("custom", url, local_ok=provider.local_provider)
    try:
        import httpx

        with (
            httpx.Client(timeout=8.0) as client,
            client.stream("GET", url, headers={"Authorization": f"Bearer {key}"}) as response,
        ):
            if response.status_code == 404:
                store.update(
                    provider_id,
                    discovery_status="unsupported",
                    last_model_sync_at=utc_now(),
                )
                return {
                    "provider_id": provider_id,
                    "status": "unsupported",
                    "models": [],
                    "count": 0,
                    "manual_allowed": True,
                    "http_status": 404,
                    "latency_ms": max(1, round((time.perf_counter() - started) * 1000)),
                }
            if response.status_code in {401, 403}:
                raise HTTPException(status_code=401, detail="authentication failed")
            if response.status_code == 429:
                raise HTTPException(status_code=429, detail="rate limited")
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="model discovery unavailable")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > 1024 * 1024:
                    raise HTTPException(status_code=502, detail="model list response too large")
                chunks.append(chunk)
            try:
                import json

                payload = json.loads(b"".join(chunks))
            except (ValueError, TypeError) as exc:
                raise HTTPException(status_code=502, detail="invalid model list response") from exc
        supported_shape = isinstance(payload, list) or (
            isinstance(payload, dict)
            and isinstance(payload.get("data", payload.get("models")), list)
        )
        if not supported_shape:
            store.update(
                provider_id,
                discovery_status="unsupported_response",
                last_model_sync_at=utc_now(),
            )
            return {
                "provider_id": provider_id,
                "status": "unsupported_response",
                "models": [],
                "count": 0,
                "manual_allowed": True,
                "http_status": 200,
                "latency_ms": max(1, round((time.perf_counter() - started) * 1000)),
            }
        models = normalize_models(payload)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="model discovery timeout") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="model discovery unreachable") from exc
    provider = store.update_discovery(provider_id, models, "success")
    return {
        "provider_id": provider_id,
        "status": "success",
        "models": [dict(item, display_name=item["id"]) for item in models],
        "count": len(models),
        "last_model_sync_at": provider.last_model_sync_at,
        "http_status": 200,
        "latency_ms": max(1, round((time.perf_counter() - started) * 1000)),
    }


@app.post("/settings/connections/providers/{provider_id}/discover-models")
def discover_custom_models(provider_id: str) -> dict[str, Any]:
    return _discover_custom_models(provider_id)


@app.post("/settings/connections/providers/{provider_id}/refresh-models")
def refresh_custom_models(provider_id: str) -> dict[str, Any]:
    return _discover_custom_models(provider_id)


@app.post("/settings/connections/providers/{provider_id}/test")
def test_custom_provider(provider_id: str) -> dict[str, Any]:
    from app.core.provider_store import models_url
    from app.memory.models import utc_now

    store = _provider_store()
    provider = store.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="custom provider not found")
    if not _secret_resolver().resolve(store.secret_key(provider_id)):
        provider = store.update(
            provider_id, health="authentication_failed", last_checked_at=utc_now()
        )
        return {"provider_id": provider_id, "status": provider.health}
    if provider.test_provider:
        provider = store.update(provider_id, health="healthy", last_checked_at=utc_now())
        return {"provider_id": provider_id, "status": provider.health}
    _validate_base_url(
        "custom",
        models_url(provider.base_url, provider.models_endpoint),
        local_ok=provider.local_provider,
    )
    try:
        result = _discover_custom_models(provider_id)
        status = "healthy" if result["status"] in {"success", "unsupported"} else "unreachable"
    except HTTPException as exc:
        status = "authentication_failed" if exc.status_code == 401 else "unreachable"
    provider = store.update(provider_id, health=status, last_checked_at=utc_now())
    return {"provider_id": provider_id, "status": provider.health}


@app.post("/settings/connections/providers/{provider_id}/test-model")
def test_custom_model(provider_id: str, body: CustomModelTestBody | None = None) -> dict[str, Any]:
    """One bounded real inference. Credential, headers and raw output never leave this endpoint."""
    import uuid

    from app.core.budget import BudgetController
    from app.core.events import init as events_init
    from app.gateway.audit import AuditLog
    from app.gateway.contracts import ModelRequest, ProviderError, ProviderErrorCode
    from app.gateway.model_gateway import ModelGateway
    from app.gateway.openai_compatible import OpenAICompatibleProvider
    from app.gateway.structured_gen import generate_structured
    from app.memory.models import utc_now

    store = _provider_store()
    provider = store.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="custom provider not found")
    if provider.test_provider:
        raise HTTPException(status_code=409, detail="real model test refuses isolated provider")
    key = _secret_resolver().resolve(store.secret_key(provider_id))
    if not key:
        raise HTTPException(status_code=409, detail="credential is not configured")
    model = (body.model if body else None) or provider.default_model
    if not model:
        raise HTTPException(status_code=409, detail="select a model before testing invocation")
    runtime_provider = OpenAICompatibleProvider(
        base_url=provider.base_url,
        api_key=key,
        default_model=model,
        enable_real=True,
        timeout_seconds=30,
        temperature=0,
        max_output_tokens=64,
        allow_local=provider.local_provider,
        chat_endpoint=provider.chat_endpoint,
        provider_name=provider.provider_name,
    )
    events_init(_data_dir())
    gateway = ModelGateway(
        provider=runtime_provider,
        budget=BudgetController(512, 0.05, max_calls=3),
        audit=AuditLog(_data_dir() / "audit.jsonl"),
        task_id="real01-model-test",
        run_id="real01-model-test",
        usage_store=_usage_store(),
    )
    request = ModelRequest(
        request_id=uuid.uuid4().hex[:16],
        task_id="real01-model-test",
        run_id="real01-model-test",
        agent_id="acceptance",
        role_type="supervisor",
        model=model,
        messages=[
            {"role": "system", "content": "Return only valid JSON with no markdown."},
            {
                "role": "user",
                "content": 'Return exactly this JSON object: {"status":"ok","number":7}',
            },
        ],
        response_schema={"status": {"type": "str"}, "number": {"type": "int"}},
        max_output_tokens=64,
        timeout_seconds=30,
        metadata={"acceptance": "REAL-01-A", "provider_id": provider_id},
    )
    telemetry: dict[str, Any] = {}
    try:
        data = generate_structured(
            gateway,
            request,
            request.response_schema or {},
            _settings(),
            max_retries=0,
            telemetry=telemetry,
        )
        if data != {"status": "ok", "number": 7}:
            raise ProviderError(
                ProviderErrorCode.SCHEMA_VALIDATION_FAILED,
                "minimal model response failed semantic validation",
                provider=provider.provider_name,
                model=model,
            )
    except ProviderError as exc:
        failure = {
            ProviderErrorCode.AUTHENTICATION_ERROR: "AUTHENTICATION_FAILED",
            ProviderErrorCode.MODEL_NOT_FOUND: "MODEL_NOT_FOUND",
            ProviderErrorCode.RATE_LIMITED: "RATE_LIMITED",
            ProviderErrorCode.TIMEOUT: "PROVIDER_TIMEOUT",
            ProviderErrorCode.PROVIDER_INTERNAL_ERROR: "PROVIDER_SERVER_ERROR",
            ProviderErrorCode.SCHEMA_VALIDATION_FAILED: "SCHEMA_INVALID",
            ProviderErrorCode.BUDGET_INSUFFICIENT: "BUDGET_EXCEEDED",
        }.get(exc.code, "RUNTIME_FAILED")
        store.update(
            provider_id,
            invocation_status=failure.lower(),
            last_invoked_at=utc_now(),
        )
        raise HTTPException(status_code=502, detail=failure) from exc
    store.update(provider_id, invocation_status="success", last_invoked_at=utc_now())
    return {
        "status": "success",
        "real_call": True,
        "provider": provider.provider_name,
        "endpoint": provider.base_url,
        "model": telemetry.get("model", model),
        "input_tokens": telemetry.get("input_tokens"),
        "output_tokens": telemetry.get("output_tokens"),
        "cached_tokens": telemetry.get("cached_tokens"),
        "total_tokens": telemetry.get("total_tokens"),
        "usage_available": telemetry.get("usage_available", False),
        "latency_ms": telemetry.get("latency_ms"),
        "estimated_cost": telemetry.get("estimated_cost"),
        "repair_attempts": telemetry.get("repair_attempts", 0),
    }


@app.put("/settings/connections/{provider}")
def save_connection(provider: str, body: ConnectionBody) -> dict[str, Any]:
    """保存连接（session/secure）。请求内 API Key 生命周期结束后立即释放。"""

    if provider not in _CONNECTION_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}")
    # Base URL 安全校验（SSRF；本地 Provider 才允许 localhost —— 010 三十六）
    if body.base_url and provider not in ("test_provider", "github_test"):
        _validate_base_url(
            provider, body.base_url, local_ok=body.local_provider or provider == "ollama"
        )
    if provider in ("github", "github_test"):
        if body.api_key:
            _secret_resolver().set(provider_key(provider), body.api_key, body.storage_mode)
    elif provider == "ollama":
        # 本地 Provider：可保存 base_url 与模型；无密钥
        _BASE_URLS["ollama"] = body.base_url or _BASE_URLS["ollama"]
        if body.models:
            _MODEL_ROLES["ollama"] = body.models
    else:
        if body.base_url:
            _BASE_URLS["openai_compatible"] = body.base_url
        if body.api_key:
            _secret_resolver().set(provider_key(provider), body.api_key, body.storage_mode)
        if body.models:
            _MODEL_ROLES[provider] = body.models
    _CONNECTION_HEALTH[provider] = "configured"
    return {"provider": provider, "configured": _provider_info(provider)["configured"]}


@app.delete("/settings/connections/{provider}/credential")
def delete_credential(provider: str) -> dict[str, Any]:
    """删除凭据（009-A 八）。"""
    if provider not in ("openai_compatible", "github", "test_provider", "github_test"):
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}")
    _secret_resolver().delete(provider_key(provider))
    _CONNECTION_HEALTH[provider] = "missing"
    return {"provider": provider, "configured": False}


@app.post("/settings/connections/{provider}/test")
def test_connection(provider: str) -> dict[str, Any]:
    """连接测试（010 三十三）：安全状态映射，绝不回传 Provider 原始错误。"""
    if provider not in _CONNECTION_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}")
    if provider == "ollama":
        _CONNECTION_HEALTH[provider] = "healthy"
        return {"status": "healthy", "detail": "local provider (no credential)"}
    key = _secret_resolver().resolve(provider_key(provider))
    if not key:
        _CONNECTION_HEALTH[provider] = "authentication_failed"
        return {"status": "authentication_failed", "detail": "no credential configured"}
    if provider in ("test_provider", "github_test"):
        _CONNECTION_HEALTH[provider] = "healthy"
        return {"status": "healthy", "detail": "test provider connected"}
    base = _BASE_URLS.get(provider) or ""
    try:
        _validate_base_url(provider, base, local_ok=provider == "ollama")
    except HTTPException as exc:
        return {"status": "unreachable", "detail": str(exc.detail)}
    # 轻量健康检查（用户主动触发；失败映射为安全状态）
    try:
        import httpx

        headers = {"Authorization": f"Bearer {key}"} if provider == "openai_compatible" else {}
        if provider == "github":
            headers = {"Authorization": f"Bearer {key}", "X-GitHub-Api-Version": "2022-11-28"}
        url = f"{base.rstrip('/')}/models" if provider == "openai_compatible" else base
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code == 200:
            _CONNECTION_HEALTH[provider] = "healthy"
            return {"status": "healthy", "detail": "connected"}
        if resp.status_code in (401, 403):
            _CONNECTION_HEALTH[provider] = "authentication_failed"
            return {"status": "authentication_failed", "detail": "authentication failed"}
        if resp.status_code == 404:
            _CONNECTION_HEALTH[provider] = "model_not_found"
            return {"status": "model_not_found", "detail": "endpoint not found"}
        if resp.status_code == 429:
            _CONNECTION_HEALTH[provider] = "rate_limited"
            return {"status": "rate_limited", "detail": "rate limited"}
        _CONNECTION_HEALTH[provider] = "unreachable"
        return {"status": "unreachable", "detail": f"http {resp.status_code}"}
    except httpx.TimeoutException:
        _CONNECTION_HEALTH[provider] = "timeout"
        return {"status": "timeout", "detail": "timeout"}
    except Exception:  # noqa: BLE001
        _CONNECTION_HEALTH[provider] = "unreachable"
        return {"status": "unreachable", "detail": "unreachable"}


@app.get("/settings/connections/{provider}/models")
def discover_models(provider: str) -> dict[str, Any]:
    """Discover selectable models. Test providers are deterministic and never use the network."""

    if provider not in _CONNECTION_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}")
    if provider in ("github", "github_test"):
        return {"supported": False, "models": [], "manual_allowed": True}
    if provider == "test_provider":
        return {
            "supported": True,
            "models": ["jarvis-test-small", "jarvis-test-pro", "jarvis-test-reasoning"],
            "manual_allowed": True,
        }
    key = _secret_resolver().resolve(provider_key(provider))
    if provider == "ollama":
        url = f"{_BASE_URLS[provider].rstrip('/')}/api/tags"
        headers: dict[str, str] = {}
    else:
        if not key:
            return {
                "supported": True,
                "models": [],
                "manual_allowed": True,
                "status": "authentication_failed",
            }
        url = f"{_BASE_URLS[provider].rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {key}"}
    try:
        import httpx

        with httpx.Client(timeout=8.0) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code != 200:
            return {
                "supported": resp.status_code != 404,
                "models": [],
                "manual_allowed": True,
                "status": "unavailable",
            }
        payload = resp.json()
        raw_models = payload.get("data", payload.get("models", []))
        models = sorted(
            {
                str(item.get("id") or item.get("name"))
                for item in raw_models
                if isinstance(item, dict) and (item.get("id") or item.get("name"))
            }
        )
        return {"supported": True, "models": models, "manual_allowed": True}
    except Exception:  # noqa: BLE001
        return {"supported": True, "models": [], "manual_allowed": True, "status": "unreachable"}


# ============ M6-A: AI Team multi-provider routing ============


class TeamRouteBody(BaseModel):
    provider_id: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    scope: Literal["global", "project"] = "global"
    project_id: str | None = Field(default=None, max_length=200)
    fallback_provider_id: str | None = Field(default=None, max_length=200)
    fallback_model: str | None = Field(default=None, max_length=300)
    token_budget: int = Field(default=4096, gt=0, le=1_000_000)
    cost_budget: float | None = Field(default=None, ge=0, le=100)


def _team_store():
    from app.gateway.multi_provider import TeamRoutingStore

    return TeamRoutingStore(_data_dir() / "runtime" / "team_routing.sqlite")


def _team_provider(provider_id: str) -> dict[str, Any] | None:
    from app.gateway.multi_provider import ProviderHealthService

    if provider_id.startswith("builtin:"):
        name = provider_id.split(":", 1)[1]
        if name not in {"openai_compatible", "ollama"}:
            return None
        info = _provider_info(name)
        return {
            "provider_id": provider_id,
            "provider_name": (
                "OpenAI Compatible" if name == "openai_compatible" else "Ollama Local"
            ),
            "configured": info["configured"],
            "storage": info["storage"],
            "health": ProviderHealthService.status(
                configured=info["configured"], health=info["health"]
            ),
            "models": sorted(set(info["models"].values())),
            "manual_allowed": True,
            "local_provider": info["local_provider"],
            "test_provider": info["test_provider"],
        }
    provider = _provider_store().get(provider_id)
    if provider is None:
        return None
    info = _custom_provider_info(provider)
    return {
        "provider_id": provider.provider_id,
        "provider_name": provider.provider_name,
        "configured": info["configured"],
        "storage": info["storage"],
        "health": ProviderHealthService.status(
            configured=info["configured"],
            health=provider.health,
            invocation_status=provider.invocation_status,
        ),
        "models": [item["id"] for item in provider.discovered_models],
        "manual_allowed": True,
        "local_provider": provider.local_provider,
        "test_provider": provider.test_provider,
    }


def _team_providers() -> list[dict[str, Any]]:
    provider_ids = ["builtin:openai_compatible", "builtin:ollama"]
    provider_ids.extend(provider.provider_id for provider in _provider_store().list())
    return [item for provider_id in provider_ids if (item := _team_provider(provider_id))]


def _team_route_card(role: str, project_id: str | None = None) -> dict[str, Any]:
    from app.gateway.contracts import ProviderError
    from app.gateway.multi_provider import ModelCapabilityRegistry, RoleModelRouter

    store = _team_store()
    try:
        decision = RoleModelRouter(store).resolve(role, project_id=project_id)
    except ProviderError:
        return {
            "role": role,
            "provider_id": None,
            "provider": None,
            "model": None,
            "source": None,
            "capability": {"text": None, "structured_output": None, "vision": None},
            "health": "WAITING_FOR_PROVIDER_CREDENTIAL",
            "latency_ms": None,
            "success_rate": None,
            "cost": None,
            "cost_label": "Cost unavailable",
            "fallback": None,
            "token_budget": None,
            "warning": None,
        }
    provider = _team_provider(decision.provider_id)
    capability = ModelCapabilityRegistry().get(decision.provider_id, decision.model)
    profile = next(
        (
            item
            for item in store.performance()
            if item.provider_id == decision.provider_id
            and item.model == decision.model
            and item.role == role
        ),
        None,
    )
    executor = None
    try:
        executor = RoleModelRouter(store).resolve("executor", project_id=project_id)
    except ProviderError:
        pass
    same_reviewer = bool(
        role == "reviewer"
        and executor
        and executor.provider_id == decision.provider_id
        and executor.model == decision.model
    )
    return {
        "role": role,
        "provider_id": decision.provider_id,
        "provider": provider["provider_name"] if provider else decision.provider_id,
        "model": decision.model,
        "source": decision.source,
        "capability": capability.model_dump(mode="json"),
        "health": provider["health"] if provider else "PROVIDER_NOT_FOUND",
        "latency_ms": profile.latency_ms_avg if profile else None,
        "success_rate": profile.success_rate if profile else None,
        "cost": profile.cost if profile else None,
        "cost_label": (
            f"${profile.cost:.6f}" if profile and profile.cost is not None else "Cost unavailable"
        ),
        "fallback": (
            {
                "provider_id": decision.fallback_provider_id,
                "model": decision.fallback_model,
            }
            if decision.fallback_provider_id
            else None
        ),
        "token_budget": decision.token_budget,
        "cost_budget": decision.cost_budget,
        "warning": "EXECUTOR_REVIEWER_NOT_INDEPENDENT" if same_reviewer else None,
    }


@app.get("/settings/ai-team/routing")
def team_routing(project_id: str | None = None) -> dict[str, Any]:
    from app.gateway.multi_provider import ROLE_MODEL_SLOTS

    return {
        "roles": [_team_route_card(role, project_id) for role in ROLE_MODEL_SLOTS],
        "providers": _team_providers(),
        "precedence": ["task", "project", "global", "configured_fallback"],
        "fallback_policy": "NO_SILENT_FALLBACK",
        "reviewer_policy": "READ_ONLY",
    }


@app.put("/settings/ai-team/routing/{role}")
def save_team_route(role: str, body: TeamRouteBody) -> dict[str, Any]:
    from app.gateway.multi_provider import ROLE_MODEL_SLOTS, ModelRoute

    if role not in ROLE_MODEL_SLOTS:
        raise HTTPException(status_code=404, detail="unknown role model slot")
    if _team_provider(body.provider_id) is None:
        raise HTTPException(status_code=404, detail="provider not found")
    if body.fallback_provider_id and _team_provider(body.fallback_provider_id) is None:
        raise HTTPException(status_code=404, detail="fallback provider not found")
    scope_id = body.project_id if body.scope == "project" else "global"
    if body.scope == "project" and not scope_id:
        raise HTTPException(status_code=400, detail="project route requires project_id")
    try:
        route = _team_store().set_route(
            ModelRoute(
                scope=body.scope,
                scope_id=scope_id or "global",
                role=role,
                provider_id=body.provider_id,
                model=body.model,
                fallback_provider_id=body.fallback_provider_id,
                fallback_model=body.fallback_model,
                token_budget=body.token_budget,
                cost_budget=body.cost_budget,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"route": route.model_dump(mode="json"), "card": _team_route_card(role, body.project_id)}


@app.delete("/settings/ai-team/routing/{role}")
def delete_team_route(
    role: str, scope: Literal["global", "project"] = "global", project_id: str | None = None
) -> dict[str, Any]:
    scope_id = project_id if scope == "project" else "global"
    if scope == "project" and not scope_id:
        raise HTTPException(status_code=400, detail="project route requires project_id")
    deleted = _team_store().delete_route(scope, scope_id or "global", role)
    return {"deleted": deleted, "role": role}


@app.get("/settings/ai-team/performance")
def team_performance() -> dict[str, Any]:
    return {
        "profiles": [
            dict(item.model_dump(mode="json"), success_rate=item.success_rate)
            for item in _team_store().performance()
        ],
        "automatic_routing": False,
    }


@app.post("/settings/ai-team/test")
def test_ai_team() -> dict[str, Any]:
    """At most one bounded real inference per configured core role; no fake success."""
    from app.gateway.contracts import ModelResponse, ProviderError
    from app.gateway.multi_provider import RoleModelRouter

    results: list[dict[str, Any]] = []
    store = _team_store()
    router = RoleModelRouter(store)
    for role in ("supervisor", "planner", "researcher", "executor", "reviewer"):
        try:
            decision = router.resolve(role)
        except ProviderError:
            results.append({"role": role, "status": "WAITING_FOR_PROVIDER_CREDENTIAL"})
            continue
        provider = _team_provider(decision.provider_id)
        if provider is None or not provider["configured"]:
            results.append(
                {
                    "role": role,
                    "provider_id": decision.provider_id,
                    "model": decision.model,
                    "status": "WAITING_FOR_PROVIDER_CREDENTIAL",
                }
            )
            continue
        if provider["test_provider"]:
            results.append(
                {
                    "role": role,
                    "provider_id": decision.provider_id,
                    "model": decision.model,
                    "status": "ISOLATED_TEST_ONLY",
                    "real_call": False,
                }
            )
            continue
        if decision.provider_id.startswith("builtin:"):
            results.append(
                {
                    "role": role,
                    "provider_id": decision.provider_id,
                    "model": decision.model,
                    "status": "NATIVE_REAL_TEST_NOT_CONFIGURED",
                    "real_call": False,
                }
            )
            continue
        try:
            telemetry = test_custom_model(
                decision.provider_id, CustomModelTestBody(model=decision.model)
            )
            response = ModelResponse(
                request_id=f"team-{role}",
                provider=str(telemetry["provider"]),
                model=str(telemetry["model"]),
                input_tokens=int(telemetry.get("input_tokens") or 0),
                output_tokens=int(telemetry.get("output_tokens") or 0),
                total_tokens=int(telemetry.get("total_tokens") or 0),
                usage_available=bool(telemetry.get("usage_available")),
                estimated_cost=telemetry.get("estimated_cost"),
                latency_ms=int(telemetry.get("latency_ms") or 0),
            )
            store.record_call(decision, response, success=True, structured_output_success=True)
            results.append(
                {
                    "role": role,
                    "provider_id": decision.provider_id,
                    "provider": telemetry["provider"],
                    "model": telemetry["model"],
                    "status": "REAL_READY",
                    "real_call": True,
                    "latency_ms": telemetry.get("latency_ms"),
                    "total_tokens": telemetry.get("total_tokens"),
                    "cost": telemetry.get("estimated_cost"),
                }
            )
        except HTTPException as exc:
            store.record_call(decision, None, success=False)
            detail = exc.detail if isinstance(exc.detail, str) else "RUNTIME_FAILED"
            results.append(
                {
                    "role": role,
                    "provider_id": decision.provider_id,
                    "model": decision.model,
                    "status": detail,
                    "real_call": False,
                }
            )
    ready = sum(item["status"] == "REAL_READY" for item in results)
    return {
        "results": results,
        "ready": ready,
        "total": len(results),
        "status": "REAL_READY" if ready == len(results) else "PARTIAL",
        "max_calls": len(results),
        "max_output_tokens_per_call": 64,
    }


# ============ M6-A: local-first JARVIS voice layer ============


class VoiceTranscriptBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    execute: bool = True


class VoiceSpeakBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@app.get("/voice")
@app.get("/voice/status")
def voice_status() -> dict[str, Any]:
    return _voice_service().status().model_dump(mode="json")


@app.get("/voice/devices")
def voice_devices() -> dict[str, Any]:
    try:
        devices = _voice_service().devices.list_devices()
    except RuntimeError as exc:
        return {"devices": [], "status": str(exc)}
    return {
        "devices": [item.model_dump(mode="json") for item in devices],
        "status": "AVAILABLE",
    }


@app.get("/voice/settings")
def voice_settings() -> dict[str, Any]:
    return _voice_service().settings.model_dump(mode="json")


@app.put("/voice/settings")
def save_voice_settings(body: VoiceSettings) -> dict[str, Any]:
    try:
        return _voice_service().update_settings(body).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/voice/session/start")
def voice_session_start() -> dict[str, Any]:
    return _voice_service().start_session().model_dump(mode="json")


@app.post("/voice/session/stop")
def voice_session_stop() -> dict[str, Any]:
    _voice_local_action("stop")
    return _voice_service().stop().model_dump(mode="json")


@app.post("/voice/session/pause")
def voice_session_pause() -> dict[str, Any]:
    return _voice_service().pause().model_dump(mode="json")


@app.post("/voice/session/resume")
def voice_session_resume() -> dict[str, Any]:
    return _voice_service().resume().model_dump(mode="json")


@app.post("/voice/ptt/start")
def voice_ptt_start() -> dict[str, Any]:
    return _voice_service().ptt_start().model_dump(mode="json")


@app.post("/voice/ptt/stop")
def voice_ptt_stop(execute: bool = True) -> dict[str, Any]:
    return _voice_service().ptt_stop(execute=execute).model_dump(mode="json")


@app.post("/voice/transcript/partial")
def voice_partial(body: VoiceTranscriptBody) -> dict[str, Any]:
    return _voice_service().update_partial(body.text).model_dump(mode="json")


@app.post("/voice/transcript/final")
def voice_final(body: VoiceTranscriptBody) -> dict[str, Any]:
    return _voice_service().submit_final(body.text, execute=body.execute).model_dump(mode="json")


@app.post("/voice/speak")
def voice_speak(body: VoiceSpeakBody) -> dict[str, Any]:
    return _voice_service().speak(body.text).model_dump(mode="json")


def _validate_base_url(provider: str, base_url: str, local_ok: bool = False) -> None:
    """Base URL 安全校验：仅 http/https；默认拒绝 localhost（SSRF，010 十二/三十六）。"""
    import re as _re

    from app.core.ssrf import blocked_host_reason

    m = _re.fullmatch(r"(https?)://([^/:]+)(?::\d{1,5})?(?:/.*)?", base_url.strip())
    if not m:
        raise HTTPException(status_code=400, detail="base_url must be http(s)://host[:port]")
    scheme, host = m.group(1), m.group(2)
    if host in ("localhost", "127.0.0.1", "::1") and not local_ok:
        raise HTTPException(status_code=400, detail="localhost only allowed for local providers")
    reason = blocked_host_reason(host)
    if reason and not (local_ok and host in ("localhost", "127.0.0.1", "::1")):
        raise HTTPException(status_code=400, detail=f"base_url blocked: {reason}")
    loopback = host in ("localhost", "127.0.0.1", "::1")
    if scheme == "http" and not (local_ok and loopback):
        raise HTTPException(
            status_code=400, detail="http base_url only allowed for loopback local providers"
        )


# security_review LOW（sa_20260808_122950）：控制面无认证——拒绝非 loopback 绑定
def _assert_loopback_bind(host: str) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(
            f"refusing to bind API to {host!r}: no-auth control plane requires "
            "loopback (use 127.0.0.1 / localhost / ::1)"
        )


if __name__ == "__main__":
    import argparse

    _ap = argparse.ArgumentParser(
        prog="ai-team-os-api", description="AI Team OS Web Control Center API"
    )
    _ap.add_argument("--host", default="127.0.0.1")
    _ap.add_argument("--port", type=int, default=8000)
    _args = _ap.parse_args()
    _assert_loopback_bind(_args.host)
    import uvicorn

    uvicorn.run("app.api.server:app", host=_args.host, port=_args.port)
