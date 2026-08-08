"""最小 FastAPI（M3-A）：任务创建 / 查询 / 恢复 / 追踪 / providers。

- POST /tasks 默认 model_mode=fake，避免意外费用（005 十七）。
- 客户端不能传 base_url 或 API Key（schema 无此字段）。
- 客户端模型覆盖经服务端允许列表校验。
- 仅限本地单用户环境，不得暴露到公网（005 二十）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.core.config import AppSettings, load_settings
from app.core.resume import ResumePayload
from app.core.schemas import ClarificationPayload
from app.gateway.contracts import ProviderError
from app.runner import (
    approval_show,
    approvals_of,
    artifact_show,
    artifacts_of,
    diff_of,
    dry_run,
    evidence_list,
    evidence_show,
    provider_health,
    resume_task,
    rollback,
    run_task,
    status_task,
    tool_catalog,
    trace_task,
)

app = FastAPI(title="AI Team OS", version="0.3.0")

# 本地单用户开发模式：不实现用户认证，文档注明不可暴露公网（005 十七/二十）
_settings_cache: AppSettings | None = None


def _data_dir() -> Path:
    return Path(os.environ.get("AI_TEAM_OS_DATA_DIR", "data"))


def _settings() -> AppSettings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = load_settings()
    return _settings_cache


class TaskCreate(BaseModel):
    goal: str = Field(min_length=1)
    project_id: str = "default"
    token_budget: int = Field(default=10000, gt=0, le=1_000_000)
    cost_budget: float = Field(default=1.0, gt=0, le=100.0)
    model_mode: str = Field(default="fake", pattern="^(fake|real)$")
    model_overrides: dict[str, str] = Field(default_factory=dict)
    # 006 十五：工具画像 / 项目别名 / 允许域名（客户端不能传绝对路径或动态 MCP）
    tool_profile: str = Field(default="readonly", pattern="^[a-z_]+$")
    project_alias: str | None = Field(default=None, max_length=100)
    allowed_domains: list[str] = Field(default_factory=list, max_length=20)


class TaskResume(BaseModel):
    clarification: str | None = None


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
        "final_result": report.state.final_result,
        "usage": report.usage,
        "call_count": report.call_count,
        "tool_call_count": report.tool_call_count,
    }


@app.get("/tasks/{run_id}")
def get_task(run_id: str) -> dict[str, Any]:
    try:
        report = status_task(run_id, data_dir=_data_dir())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "task_id": report.task_id,
        "run_id": report.run_id,
        "status": report.status,
        "model_mode": report.state.model_mode,
        "clarified_goal": report.state.clarified_goal,
        "pending_clarification_id": report.state.pending_clarification_id,
        "final_result": report.state.final_result,
        "usage": report.usage,
        "tool_call_count": report.tool_call_count,
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
    from app.core.approval import ApprovalError, ApprovalService
    from app.core.schemas import ApprovalPayload

    data_dir = _data_dir()
    record = approval_show(approval_id, data_dir=data_dir)  # 404 或返回记录
    task_id = record["task_id"]
    approval = ApprovalService(
        storage_path=data_dir / "runtime" / "workspaces" / task_id / "approvals.jsonl"
    )
    try:
        approval.decide(approval_id, "approved", (body.reason if body else None))
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # 恢复任务（run_id 从审批记录取；未记录 run_id 时用 task_id 兜底）
    run_id = record.get("run_id") or task_id
    try:
        report = resume_task(
            run_id,
            payload=ApprovalPayload(
                approval_id=approval_id, decision="approved", reason=(body.reason if body else None)
            ),
            data_dir=data_dir,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "approval_id": approval_id,
        "status": "approved",
        "task_status": report.state.current_status,
    }


@app.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, body: ApprovalDecisionBody | None = None) -> dict[str, Any]:
    """拒绝：不应用补丁，任务标记未实施（GT-W03）。"""
    from app.core.approval import ApprovalError, ApprovalService
    from app.core.schemas import ApprovalPayload

    data_dir = _data_dir()
    record = approval_show(approval_id, data_dir=data_dir)
    task_id = record["task_id"]
    approval = ApprovalService(
        storage_path=data_dir / "runtime" / "workspaces" / task_id / "approvals.jsonl"
    )
    try:
        approval.decide(approval_id, "rejected", (body.reason if body else None))
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run_id = record.get("run_id") or task_id
    try:
        report = resume_task(
            run_id,
            payload=ApprovalPayload(
                approval_id=approval_id, decision="rejected", reason=(body.reason if body else None)
            ),
            data_dir=data_dir,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


@app.get("/agents")
def agents() -> list[dict[str, Any]]:
    """Agent 目录（010 第二十二部分，本阶段只读）。"""
    from app.core.registry import default_registry

    registry = default_registry()
    out = []
    for agent in registry.all():
        out.append(
            {
                "agent_id": agent.agent_id,
                "role": agent.role_type,
                "display_name": agent.display_name,
                "model": agent.model_scenario,
                "enabled": agent.enabled,
                "token_limit": agent.token_limit,
                "max_tool_calls": agent.max_tool_calls,
                "allowed_tools": sorted(agent.allowed_tools),
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
    real_enabled = getattr(settings.model, "enable_real", False)
    return {
        "model_provider": {
            "name": "openai_compatible",
            "status": "Configured" if real_enabled else "Missing",
            "base_url_configured": bool(getattr(settings.model, "base_url", None)),
            "api_key_configured": bool(getattr(settings.model, "api_key", None)),
        },
        "github": {
            "status": "Configured" if os.environ.get("AI_TEAM_GITHUB_TOKEN") else "Missing",
            "token_configured": bool(os.environ.get("AI_TEAM_GITHUB_TOKEN")),
        },
        "real_model": {"status": "Enabled" if real_enabled else "Disabled"},
        "allowed_read_roots": {"count": len(allowed_read_roots())},
        "mcp": {"servers": 0, "status": "Disabled"},
        "network_isolation": "Best Effort",
        "sandbox": {"status": "Online" if allowed_read_roots() else "Disabled"},
    }


@app.get("/tasks/{run_id}/events")
def task_events(run_id: str) -> Any:
    """SSE 实时事件（010 第十四部分）：Last-Event-ID 支持 replay。

    轮询 EventStore（sequence > last），无新事件时保持连接（心跳注释行）。
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
        status_task(run_id, data_dir=_data_dir())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")

    def _stream():
        import asyncio
        import json as _json

        last = 0
        idle = 0
        while True:
            events = store.list_events(run_id=run_id, after_sequence=last)
            for ev in events:
                data = _json.dumps(ev.model_dump(), ensure_ascii=False)
                yield f"id: {ev.sequence}\nevent: {ev.event_type}\ndata: {data}\n\n"
                last = ev.sequence
                idle = 0
            if not events:
                idle += 1
                if idle >= 3:
                    # 任务终态后补发状态事件再结束；否则保持心跳
                    try:
                        st = status_task(run_id, data_dir=_data_dir())
                        if st.state.current_status in ("completed", "failed"):
                            payload = _json.dumps(
                                {"status": st.state.current_status}, ensure_ascii=False
                            )
                            yield (f"id: {last}\nevent: task_status_changed\ndata: {payload}\n\n")
                            return
                    except KeyError:
                        return
                yield ": keepalive\n\n"
            yield f'id: {last}\nevent: ping\ndata: {{"sequence": {last}}}\n\n'
            asyncio.sleep(1.0)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============ Connections / Secret 管理（010 三十~三十六 / 009-A） ============


class ConnectionBody(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=2000)
    models: dict[str, str] | None = (
        None  # 角色 → 模型（default/supervisor/planner/researcher/executor/reviewer）
    )
    storage_mode: str = Field(default="session", pattern="^(session|secure)$")
    local_provider: bool = False  # 仅 Ollama 本地 Provider 允许 localhost（010 三十六）


_resolver = None  # 惰性初始化（依赖 data_dir）


def _secret_resolver():
    global _resolver
    if _resolver is None:
        from app.core.secret_store import default_resolver

        _resolver = default_resolver(_data_dir())
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
        "health": "configured" if configured else "missing",
        "local_provider": provider == "ollama",
    }


_BASE_URLS = {
    "openai_compatible": "",
    "github": "https://api.github.com",
    "ollama": "http://127.0.0.1:11434",
}

_MODEL_ROLES: dict[str, dict[str, str]] = {
    "openai_compatible": {},
    "github": {},
    "ollama": {},
}


def provider_key(provider: str) -> str:
    if provider == "github":
        return "github.token"
    return f"{provider}.api_key"


@app.get("/settings/connections")
def connections_status() -> dict[str, Any]:
    """Connections 状态（009-A 八；禁止返回任何 Secret）。"""
    return {p: _provider_info(p) for p in ("openai_compatible", "github", "ollama")}


@app.put("/settings/connections/{provider}")
def save_connection(provider: str, body: ConnectionBody) -> dict[str, Any]:
    """保存连接（session/secure）。请求内 API Key 生命周期结束后立即释放。"""

    if provider not in ("openai_compatible", "github", "ollama"):
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}")
    # Base URL 安全校验（SSRF；本地 Provider 才允许 localhost —— 010 三十六）
    if body.base_url:
        _validate_base_url(
            provider, body.base_url, local_ok=body.local_provider or provider == "ollama"
        )
    if provider == "github":
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
            _MODEL_ROLES["openai_compatible"] = body.models
    return {"provider": provider, "configured": _provider_info(provider)["configured"]}


@app.delete("/settings/connections/{provider}/credential")
def delete_credential(provider: str) -> dict[str, Any]:
    """删除凭据（009-A 八）。"""
    if provider not in ("openai_compatible", "github"):
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}")
    _secret_resolver().delete(provider_key(provider))
    return {"provider": provider, "configured": False}


@app.post("/settings/connections/{provider}/test")
def test_connection(provider: str) -> dict[str, Any]:
    """连接测试（010 三十三）：安全状态映射，绝不回传 Provider 原始错误。"""
    if provider not in ("openai_compatible", "github", "ollama"):
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}")
    if provider == "ollama":
        return {"status": "healthy", "detail": "local provider (no credential)"}
    key = _secret_resolver().resolve(provider_key(provider))
    if not key:
        return {"status": "authentication_failed", "detail": "no credential configured"}
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
            return {"status": "healthy", "detail": "connected"}
        if resp.status_code in (401, 403):
            return {"status": "authentication_failed", "detail": "authentication failed"}
        if resp.status_code == 404:
            return {"status": "model_not_found", "detail": "endpoint not found"}
        if resp.status_code == 429:
            return {"status": "rate_limited", "detail": "rate limited"}
        return {"status": "unreachable", "detail": f"http {resp.status_code}"}
    except httpx.TimeoutException:
        return {"status": "timeout", "detail": "timeout"}
    except Exception:  # noqa: BLE001
        return {"status": "unreachable", "detail": "unreachable"}


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
    if scheme == "http" and not local_ok:
        raise HTTPException(
            status_code=400, detail="http base_url only allowed for local providers"
        )
