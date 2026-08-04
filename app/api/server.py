"""最小 FastAPI（M1）：任务创建与查询。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.core.state import TaskState
from app.runner import run_task

app = FastAPI(title="AI Team OS", version="0.1.0")

_TASKS: dict[str, TaskState] = {}


class TaskCreate(BaseModel):
    goal: str = Field(min_length=1)
    project_id: str = "default"
    token_budget: int = Field(default=10000, gt=0)
    cost_budget: float = Field(default=1.0, gt=0)


def _data_dir() -> Path:
    return Path(os.environ.get("AI_TEAM_OS_DATA_DIR", "data"))


@app.post("/tasks")
def create_task(body: TaskCreate) -> dict[str, Any]:
    report = run_task(
        body.goal,
        token_budget=body.token_budget,
        cost_budget=body.cost_budget,
        project_id=body.project_id,
        data_dir=_data_dir(),
    )
    _TASKS[report.task_id] = report.state
    return {
        "task_id": report.task_id,
        "status": report.status,
        "final_result": report.state.final_result,
        "usage": report.usage,
        "call_count": report.call_count,
    }


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> TaskState:
    if task_id not in _TASKS:
        raise HTTPException(status_code=404, detail="task not found")
    return _TASKS[task_id]
