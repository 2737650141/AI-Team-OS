"""Bounded REAL-01 structured-output acceptance; never reads or writes credential values."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.core.budget import BudgetController
from app.core.config import load_settings
from app.core.events import init as events_init
from app.core.plan_validator import validate_plan
from app.core.registry import default_registry
from app.core.schemas import Plan, ResearchReport, ReviewResult
from app.gateway.audit import AuditLog
from app.gateway.contracts import ModelRequest
from app.gateway.model_gateway import ModelGateway
from app.gateway.structured_gen import generate_structured
from app.memory.models import MemoryProposal
from app.memory.policy import MemoryPolicy
from app.runner import build_provider

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "artifacts" / "acceptance" / "real-model"
MODEL = "deepseek-v4-flash"


CASES: list[tuple[str, dict[str, Any], str, type[BaseModel]]] = [
    (
        "planner",
        {"goal": {"type": "str"}, "subtasks": {"type": "list"}},
        """Return only JSON for a Plan. Goal: inspect a tiny Python project and plan a minimal
fix for a failing test. Include exactly two subtasks: researcher first, then executor depending
on researcher. Each subtask needs subtask_id, title, objective, dependencies, assigned_role,
input_refs, expected_output, acceptance_criteria, required_tools, token_budget <= 1000, and
tool_call_budget <= 4. Use assigned_role researcher then executor. Researcher required_tools
must be [\"local_read_text\"]. Executor required_tools must be [\"sandbox_apply_patch\"].""",
        Plan,
    ),
    (
        "researcher",
        {
            "summary": {"type": "str"},
            "claims": {"type": "list"},
            "evidence_refs": {"type": "list"},
            "unverified_items": {"type": "list"},
            "confidence": {"type": "float"},
        },
        """Return only JSON for a ResearchReport. Evidence e1 says function is_even returns
value % 2 == 1 while tests expect True for 2 and False for 3. Include one Claim object with
claim_id, text, evidence_ids [\"e1\"], confidence; evidence_refs [\"e1\"]; no unverified items.""",
        ResearchReport,
    ),
    (
        "reviewer",
        {
            "verdict": {"type": "str"},
            "issues": {"type": "list"},
            "rework_targets": {"type": "list"},
            "accepted_claims": {"type": "list"},
            "rejected_claims": {"type": "list"},
        },
        """Return only JSON for a ReviewResult. Deterministic tests passed and patch hash was
verified. verdict must be pass, issues/rework_targets/rejected_claims empty, accepted_claims
contains c1.""",
        ReviewResult,
    ),
    (
        "memory",
        {
            "proposal_id": {"type": "str"},
            "memory_type": {"type": "str"},
            "subject": {"type": "str"},
            "predicate": {"type": "str"},
            "proposed_value": {"type": "str"},
            "reason": {"type": "str"},
            "source_type": {"type": "str"},
            "source_ref": {"type": "str"},
            "confidence": {"type": "float"},
            "privacy_level": {"type": "str"},
            "confirmation_required": {"type": "bool"},
            "created_at": {"type": "str"},
            "status": {"type": "str"},
            "tags": {"type": "list"},
            "retention": {"type": "str"},
        },
        """Return only JSON for a MemoryProposal candidate: proposal_id mp-real01,
memory_type procedural_preference, subject response_language, predicate prefer,
proposed_value 优先使用中文, reason user asked in the task, source_type model_inference,
source_ref real01, confidence 0.9, privacy_level personal, confirmation_required true,
created_at 2026-08-09T00:00:00+00:00, status proposed, tags [interaction_preference],
retention manual. Do not add fields containing credentials.""",
        MemoryProposal,
    ),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    events_init(DATA)
    provider = build_provider(load_settings(), DATA)
    budget = BudgetController(30_000, 0.50, max_calls=12)
    gateway = ModelGateway(provider, budget, AuditLog(DATA / "audit.jsonl"), "real01-structured")
    results: dict[str, Any] = {}
    first_pass = 0
    total_repairs = 0
    for name, schema, prompt, model_type in CASES:
        def semantic_validate(payload: dict[str, Any]) -> BaseModel:
            candidate = model_type.model_validate(payload)
            if isinstance(candidate, Plan):
                validate_plan(candidate, default_registry(), 10_000)
            if isinstance(candidate, ResearchReport):
                if not candidate.claims or candidate.claims[0].evidence_ids != ["e1"]:
                    raise ValueError("research claims must be bound to evidence e1")
            if isinstance(candidate, ReviewResult) and candidate.verdict != "pass":
                raise ValueError("review verdict must be pass after deterministic checks pass")
            return candidate

        request = ModelRequest(
            request_id=uuid.uuid4().hex[:16],
            task_id="real01-structured",
            run_id="real01-structured",
            agent_id=name,
            role_type="planner" if name == "memory" else name,
            model=MODEL,
            messages=[
                {"role": "system", "content": "Return only valid JSON. Never include secrets."},
                {"role": "user", "content": prompt},
            ],
            response_schema=schema,
            max_output_tokens=1800,
            metadata={"acceptance": "REAL-01-B", "case": name},
        )
        telemetry: dict[str, Any] = {}
        data = generate_structured(
            gateway,
            request,
            schema,
            load_settings(),
            max_retries=0,
            telemetry=telemetry,
            semantic_validator=semantic_validate,
        )
        validated = model_type.model_validate(data)
        if isinstance(validated, Plan):
            validate_plan(validated, default_registry(), 10_000)
        if isinstance(validated, ResearchReport):
            assert validated.claims and validated.claims[0].evidence_ids == ["e1"]
        if isinstance(validated, ReviewResult):
            assert validated.verdict == "pass"
        safe: dict[str, Any] = {
            "real_call": True,
            "provider": telemetry.get("provider"),
            "model": telemetry.get("model"),
            "validated_type": model_type.__name__,
            "repair_attempts": telemetry.get("repair_attempts", 0),
            "input_tokens": telemetry.get("input_tokens"),
            "output_tokens": telemetry.get("output_tokens"),
            "cached_tokens": telemetry.get("cached_tokens"),
            "total_tokens": telemetry.get("total_tokens"),
            "latency_ms": telemetry.get("latency_ms"),
            "validated_output": validated.model_dump(mode="json"),
        }
        if isinstance(validated, MemoryProposal):
            decision = MemoryPolicy().evaluate(validated, trusted_user_source=False)
            safe["governance"] = {
                "direct_write_allowed": decision.allowed,
                "status": decision.status,
                "reason": decision.reason,
            }
        repairs = int(telemetry.get("repair_attempts", 0))
        first_pass += int(repairs == 0)
        total_repairs += repairs
        results[name] = safe
        (OUT / f"{name}.json").write_text(
            json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary = {
        "real_call": True,
        "provider": getattr(provider, "provider_name", "unknown"),
        "model": MODEL,
        "cases": len(CASES),
        "first_success_rate": first_pass / len(CASES),
        "repair_attempts": total_repairs,
        "final_success_rate": 1.0,
        "budget_usage": budget.usage,
        "results": {
            name: {
                key: value
                for key, value in result.items()
                if key not in {"validated_output"}
            }
            for name, result in results.items()
        },
    }
    (OUT / "structured_output.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
