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
