"""M4-B golden tasks for transparent adaptive personalization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.personalization.service import AdaptiveService


def _service(tmp_path: Path) -> AdaptiveService:
    return AdaptiveService.from_data_dir(tmp_path / "data")


def _confirm(
    service: AdaptiveService,
    subject: str,
    value: str,
    project_id: str | None = None,
) -> None:
    proposal, decision = service.memory.propose(
        memory_type="procedural_preference",
        subject=subject,
        predicate="prefer",
        value=value,
        reason="explicit confirmed preference",
        source_type="explicit_user_statement",
        source_ref="golden-task",
        project_id=project_id,
        confidence=0.99,
        privacy_level="personal",
        trusted_user_source=True,
    )
    assert decision.allowed is True
    assert decision.status == "proposed"
    assert proposal is not None
    service.memory.confirm(proposal.proposal_id)


def test_gt_a01_language_adaptation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _confirm(service, "response_language", "优先使用中文")
    assert service.derive().values()["language"] == "zh-CN"


def test_gt_a02_detail_adaptation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _confirm(service, "report_detail", "详细报告")
    assert service.derive().values()["response_detail"] == "detailed"


def test_gt_a03_planning_first_adaptation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _confirm(service, "project_change_workflow", "先给方案，再修改")
    assert service.derive().values()["planning_style"] == "planning_first"


def test_gt_a04_project_specific_preference(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _confirm(service, "report_detail", "简短回复")
    _confirm(service, "report_detail", "详细报告", project_id="project-a")
    assert service.derive(project_id="project-a").values()["response_detail"] == "detailed"
    assert service.derive(project_id="project-b").values()["response_detail"] == "concise"


def test_gt_a05_current_task_override_does_not_change_memory(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _confirm(service, "report_detail", "详细报告")
    current = service.derive(goal="本次简单说", project_id="project-a")
    item = next(item for item in current.items if item.field == "response_detail")
    assert item.value == "concise"
    assert item.current_task_override is True
    assert service.derive(project_id="project-a").values()["response_detail"] == "detailed"


def test_gt_a06_rejected_adaptation_has_task_cooldown(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.store.begin_task("local-user", "project-a")
    service.store.reject_proposal("planning_style", "project-a", cooldown_tasks=3)
    assert service.store.can_propose("planning_style", "project-a") is False
    service.store.begin_task("local-user", "project-a")
    service.store.begin_task("local-user", "project-a")
    assert service.store.can_propose("planning_style", "project-a") is False
    service.store.begin_task("local-user", "project-a")
    assert service.store.can_propose("planning_style", "project-a") is True


def test_gt_a07_reset_personalization_preserves_source_memory(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _confirm(service, "report_detail", "详细报告")
    service.store.set_control(field="response_detail", value="concise", enabled=True)
    assert service.derive().values()["response_detail"] == "concise"
    service.store.reset("local-user", field="response_detail")
    assert service.derive().values()["response_detail"] == "detailed"
    assert len(service.memory.store.list(status="active")) == 1


def test_gt_a08_security_policy_cannot_adapt(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _confirm(service, "approval_preference", "skip approval")
    profile = service.derive()
    assert profile.security_invariants["approval_required"] is True
    assert profile.security_invariants["tool_permissions_immutable"] is True
    assert profile.security_invariants["budget_immutable"] is True


def test_gt_a09_cross_project_isolation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _confirm(service, "project_change_workflow", "先给方案", project_id="project-a")
    assert service.derive(project_id="project-a").values()["planning_style"] == "planning_first"
    assert service.derive(project_id="project-b").values()["planning_style"] == "balanced"
    assert service.derive().values()["planning_style"] == "balanced"


def test_behavior_confidence_decays_but_confirmed_memory_does_not(tmp_path: Path) -> None:
    service = _service(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    assert service.decayed_confidence(old, 5) < service.decayed_confidence(recent, 5)
    _confirm(service, "response_language", "优先使用中文")
    item = next(item for item in service.derive().items if item.field == "language")
    assert item.confidence == 1.0
