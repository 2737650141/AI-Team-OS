"""pytest fixtures（M1）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.budget import BudgetController
from app.gateway.audit import AuditLog
from app.gateway.model_gateway import DeterministicFakeModel, ModelGateway
from app.gateway.tool_gateway import ToolGateway
from app.tools.fixture_repo import DangerousWriteTool, FixtureRepositoryLookupTool

FIXTURE_REPOS = Path(__file__).parent / "fixtures" / "repos.json"


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture()
def audit(data_dir: Path) -> AuditLog:
    return AuditLog(data_dir / "audit.jsonl")


@pytest.fixture()
def budget() -> BudgetController:
    return BudgetController(token_budget=10000, cost_budget=1.0)


@pytest.fixture()
def model_gateway(audit: AuditLog) -> ModelGateway:
    return ModelGateway(
        provider=DeterministicFakeModel(),
        budget=BudgetController(token_budget=10000, cost_budget=1.0),
        audit=audit,
        task_id="t1",
    )


@pytest.fixture()
def tool_gateway(audit: AuditLog) -> ToolGateway:
    gw = ToolGateway(audit=audit, task_id="t1")
    gw.register(FixtureRepositoryLookupTool(FIXTURE_REPOS).spec())
    gw.register(DangerousWriteTool().spec())
    return gw
