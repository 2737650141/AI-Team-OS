"""最小 FastAPI 测试（M1）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.server import app

client = TestClient(app)


def test_create_and_get_task() -> None:
    resp = client.post(
        "/tasks",
        json={"goal": "你好，AI Team OS", "token_budget": 5000, "cost_budget": 0.5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"

    got = client.get(f"/tasks/{body['run_id']}")
    assert got.status_code == 200
    assert got.json()["run_id"] == body["run_id"]
    assert got.json()["final_result"] is not None


def test_get_missing_task() -> None:
    resp = client.get("/tasks/not-exist")
    assert resp.status_code == 404


def test_create_task_validation() -> None:
    resp = client.post("/tasks", json={"goal": "x", "token_budget": 0})
    assert resp.status_code == 422
