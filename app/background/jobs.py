"""M7-A4B: Background Jobs condition-watch runtime.

APScheduler owns WHEN through the A4A scheduler foundation. This module owns
the fixed trusted dispatcher, safe job CRUD, deterministic condition
fingerprints, condition baseline persistence, and the governed background_job
tool. User-visible notification delivery belongs to M7-A4C and is deliberately
not imported here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.background.scheduler import get_scheduler, shutdown_scheduler
from app.tools.spec import RiskLevel, ToolSpec

DEFAULT_MAX_INSTANCES = 1
DEFAULT_COALESCE = True
DEFAULT_MISFIRE_GRACE = 120  # seconds; bounded catch-up, no burst


# --------------------------------------------------------------------------
# Condition fingerprint (deterministic, evidence-based — never LLM prose)
# --------------------------------------------------------------------------

def fingerprint_records(records: list[dict[str, Any]]) -> str:
    """Stable fingerprint from structured records (sorted job id/title/url).

    Used for condition watch: same records -> same fingerprint (NO_CHANGE);
    different records -> different fingerprint (CONDITION_TRIGGERED).
    Never compares LLM summary text.
    """
    keys = []
    for record in records:
        job_id = str(record.get("job_id") or record.get("JobAdId") or record.get("Id") or "")
        title = str(record.get("title") or record.get("JobAdName") or record.get("name") or "")
        url = str(record.get("url") or record.get("source_url") or "")
        keys.append(f"{job_id}|{title}|{url}")
    blob = json.dumps(sorted(keys), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


# --------------------------------------------------------------------------
# Fixed trusted dispatcher (the ONLY callable persisted into the job store)
# --------------------------------------------------------------------------

def execute_background_job(
    job_id: str,
    instruction: str,
    task_kind: str = "langgraph",
    data_dir: str = "data",
    run_now: bool = False,
    last_fingerprint: str = "",
    last_notified_fingerprint: str = "",
) -> str:
    """Run the normal LangGraph task synchronously from APScheduler.

    ``last_notified_fingerprint`` remains an unused primitive compatibility
    argument for persisted jobs from the mixed pre-reconstruction workspace.
    Notification delivery is intentionally outside A4B.
    """
    from app.runner import run_task

    report = run_task(
        goal=instruction,
        token_budget=150_000,
        cost_budget=0.4,
        project_id=f"bg-{job_id}",
        data_dir=Path(data_dir),
        model_mode="real",
        max_model_calls=15,
        routing_intent="EXPLICIT",
        routing_mode="BALANCED",
    )
    run_id = report.run_id or ""
    if task_kind == "condition":
        _condition_check(job_id, report, last_fingerprint, data_dir)
    return run_id


def _condition_check(
    job_id: str,
    report: Any,
    previous_fingerprint: str,
    data_dir: str,
) -> str:
    """Compare structured crawler records with the persisted baseline.

    Status contract:
      CHECK_FAILED          run/tool failure or no verifiable records
      BASELINE_ESTABLISHED  first successful check (previous was empty)
      NO_CHANGE             same fingerprint as previous
      CONDITION_TRIGGERED   fingerprint differs from previous

    Only a VERIFIABLE check may update the persisted fingerprint. The
    previous baseline survives failures (never overwritten).
    """
    state = getattr(report, "state", None)
    if state is None:
        return "CHECK_FAILED"
    tool_calls = list(getattr(state, "tool_calls", None) or [])
    records: list[dict[str, Any]] = []
    saw_crawler = False
    for tool_call in tool_calls:
        tool_name = tool_call.tool if hasattr(tool_call, "tool") else tool_call.get("tool")
        summary = (
            tool_call.result_summary
            if hasattr(tool_call, "result_summary")
            else tool_call.get("result_summary", "")
        )
        if tool_name != "web_crawl_extract" or not summary:
            continue
        saw_crawler = True
        try:
            data = json.loads(str(summary).replace("'", '"')) if isinstance(summary, str) else {}
        except (ValueError, TypeError):
            data = {}
        if data.get("ok") is False:
            return "CHECK_FAILED"
        if data.get("status") == "zero_results":
            # A verifiable empty snapshot is a valid baseline.
            continue
        for record in data.get("records") or []:
            if isinstance(record, dict):
                records.append(record)

    # A search-only run is not a condition baseline.
    if not saw_crawler:
        return "CHECK_FAILED"

    current = fingerprint_records(records)
    if not previous_fingerprint:
        status = "BASELINE_ESTABLISHED"
    elif current == previous_fingerprint:
        status = "NO_CHANGE"
    else:
        status = "CONDITION_TRIGGERED"
    _persist_fingerprint(job_id, current, data_dir)
    return status


def _persist_fingerprint(job_id: str, fingerprint: str, data_dir: str) -> None:
    """Persist a verified baseline through APScheduler's safe job API.

    Missing jobs are allowed for isolated pure-condition tests that exercise
    status semantics without registering a schedule. Once a persisted job is
    present, any store/modify failure is raised to the scheduler caller rather
    than silently discarded.
    """
    scheduler = get_scheduler(data_dir)
    job = scheduler.get_job(job_id)
    if job is None:
        return
    kwargs = dict(job.kwargs or {})
    kwargs["last_fingerprint"] = fingerprint
    try:
        scheduler.modify_job(job_id, kwargs=kwargs)
    except Exception as exc:  # noqa: BLE001 — persistence failure is critical
        raise RuntimeError(f"condition fingerprint persistence failed: {job_id}") from exc


# --------------------------------------------------------------------------
# Job helpers (thin adapters over A4A scheduler wheel APIs)
# --------------------------------------------------------------------------

def create_job(
    *,
    job_id: str,
    instruction: str,
    schedule_type: str,
    delay_seconds: int = 0,
    run_at_local: str = "",
    interval_seconds: int = 0,
    cron_expression: str = "",
    data_dir: str = "data",
    task_kind: str = "langgraph",
    last_fingerprint: str = "",
) -> dict[str, Any]:
    """Create a persistent schedule using only safe primitive arguments."""
    if task_kind not in ("langgraph", "condition"):
        return {
            "ok": False,
            "code": "invalid_task_kind",
            "error": f"unknown task_kind {task_kind}",
        }
    scheduler = get_scheduler(data_dir)
    kwargs: dict[str, Any] = {
        "job_id": job_id,
        "instruction": instruction,
        "task_kind": task_kind,
        "data_dir": data_dir,
    }
    if last_fingerprint:
        kwargs["last_fingerprint"] = last_fingerprint

    if schedule_type == "once":
        if delay_seconds > 0:
            run_at = datetime.now().astimezone() + timedelta(seconds=delay_seconds)
        elif run_at_local:
            run_at = datetime.fromisoformat(run_at_local)
        else:
            return {
                "ok": False,
                "code": "invalid_schedule",
                "error": "once requires delay_seconds or run_at_local",
            }
        trigger = "date"
        trigger_args: dict[str, Any] = {"run_date": run_at}
        misfire_grace = max(DEFAULT_MISFIRE_GRACE, 60)
    elif schedule_type == "interval":
        if interval_seconds <= 0:
            return {
                "ok": False,
                "code": "invalid_schedule",
                "error": "interval requires interval_seconds > 0",
            }
        trigger = "interval"
        trigger_args = {"seconds": interval_seconds}
        misfire_grace = DEFAULT_MISFIRE_GRACE
    elif schedule_type == "cron":
        if not cron_expression:
            return {
                "ok": False,
                "code": "invalid_schedule",
                "error": "cron requires cron_expression",
            }
        parts = cron_expression.strip().split()
        if len(parts) != 5:
            return {
                "ok": False,
                "code": "invalid_schedule",
                "error": "cron_expression must have 5 fields",
            }
        trigger = "cron"
        trigger_args = {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }
        misfire_grace = DEFAULT_MISFIRE_GRACE
    else:
        return {
            "ok": False,
            "code": "invalid_schedule",
            "error": f"unknown schedule_type {schedule_type}",
        }

    scheduler.add_job(
        execute_background_job,
        trigger=trigger,
        **trigger_args,
        id=job_id,
        kwargs=kwargs,
        replace_existing=True,
        max_instances=DEFAULT_MAX_INSTANCES,
        coalesce=DEFAULT_COALESCE,
        misfire_grace_time=misfire_grace,
    )
    job = scheduler.get_job(job_id)
    return {
        "ok": True,
        "job_id": job_id,
        "schedule_type": schedule_type,
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "status": "SCHEDULED",
    }


def list_jobs(data_dir: str = "data") -> dict[str, Any]:
    scheduler = get_scheduler(data_dir)
    output = []
    for job in sorted(scheduler.get_jobs(), key=lambda item: str(item.next_run_time or "")):
        safe: dict[str, Any] = {
            "job_id": job.id,
            "schedule": str(job.trigger),
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "paused": job.next_run_time is None,
        }
        kwargs = job.kwargs or {}
        if isinstance(kwargs, dict) and "instruction" in kwargs:
            safe["instruction"] = str(kwargs["instruction"])[:200]
        output.append(safe)
    return {"ok": True, "jobs": output}


def job_status(job_id: str, data_dir: str = "data") -> dict[str, Any]:
    scheduler = get_scheduler(data_dir)
    job = scheduler.get_job(job_id)
    if job is None:
        return {"ok": False, "code": "job_not_found", "job_id": job_id}
    return {
        "ok": True,
        "job_id": job_id,
        "schedule": str(job.trigger),
        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        "paused": job.next_run_time is None,
    }


def pause_job(job_id: str, data_dir: str = "data") -> dict[str, Any]:
    scheduler = get_scheduler(data_dir)
    if scheduler.get_job(job_id) is None:
        return {"ok": False, "code": "job_not_found", "job_id": job_id}
    scheduler.pause_job(job_id)
    return {"ok": True, "job_id": job_id, "status": "PAUSED"}


def resume_job(job_id: str, data_dir: str = "data") -> dict[str, Any]:
    scheduler = get_scheduler(data_dir)
    if scheduler.get_job(job_id) is None:
        return {"ok": False, "code": "job_not_found", "job_id": job_id}
    scheduler.resume_job(job_id)
    return {"ok": True, "job_id": job_id, "status": "RESUMED"}


def cancel_job(job_id: str, data_dir: str = "data") -> dict[str, Any]:
    scheduler = get_scheduler(data_dir)
    if scheduler.get_job(job_id) is None:
        return {"ok": False, "code": "job_not_found", "job_id": job_id}
    scheduler.remove_job(job_id)
    return {"ok": True, "job_id": job_id, "status": "CANCELLED"}


# --------------------------------------------------------------------------
# Governed tool (create/list/status/pause/resume/cancel)
# --------------------------------------------------------------------------

class BackgroundJobTool:
    """Manage persistent schedules through the fixed A4B dispatcher."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="background_job",
            description=(
                "管理持久后台任务调度（APScheduler）。action=create: 用 "
                "schedule_type(once/interval/cron)+delay_seconds/run_at_local/"
                "interval_seconds/cron_expression + instruction 创建任务；"
                "task_kind 可选 langgraph/condition；action=list/status/pause/"
                "resume/cancel 管理现有任务。任务到点后由系统以 LangGraph 运行。"
            ),
            input_schema={
                "action": "str",
                "job_id": "str",
                "instruction": "str",
                "schedule_type": "str",
                "task_kind": "str",
                "delay_seconds": "int",
                "run_at_local": "str",
                "interval_seconds": "int",
                "cron_expression": "str",
            },
            risk_level=RiskLevel.SENSITIVE,
            read_only=False,
            handler=self.handler,
            roles=("researcher",),
            max_result_bytes=64 * 1024,
            permission_risk="low",
        )

    def handler(
        self,
        action: str,
        job_id: str = "",
        instruction: str = "",
        schedule_type: str = "once",
        task_kind: str = "langgraph",
        delay_seconds: int = 0,
        run_at_local: str = "",
        interval_seconds: int = 0,
        cron_expression: str = "",
    ) -> dict[str, Any]:
        import os

        data_dir = os.environ.get("AI_TEAM_OS_DATA_DIR", "data")
        if action == "create":
            if not job_id or not instruction:
                return {
                    "ok": False,
                    "code": "invalid_args",
                    "error": "create requires job_id and instruction",
                }
            return create_job(
                job_id=job_id,
                instruction=instruction,
                schedule_type=schedule_type,
                delay_seconds=delay_seconds,
                run_at_local=run_at_local,
                interval_seconds=interval_seconds,
                cron_expression=cron_expression,
                data_dir=data_dir,
                task_kind=task_kind,
            )
        if action == "list":
            return list_jobs(data_dir)
        if action == "status":
            return job_status(job_id, data_dir)
        if action == "pause":
            return pause_job(job_id, data_dir)
        if action == "resume":
            return resume_job(job_id, data_dir)
        if action == "cancel":
            return cancel_job(job_id, data_dir)
        return {"ok": False, "code": "invalid_action", "error": f"unknown action {action}"}


__all__ = [
    "BackgroundJobTool",
    "cancel_job",
    "create_job",
    "execute_background_job",
    "fingerprint_records",
    "get_scheduler",
    "job_status",
    "list_jobs",
    "pause_job",
    "resume_job",
    "shutdown_scheduler",
]
