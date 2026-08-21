from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.api.server as server
from app.api.server import app
from app.core.provider_store import ProviderStore, models_url, normalize_models
from app.core.secret_store import process_resolver
from app.gateway.router import build_router
from app.runner import _settings_with_custom_routes, build_provider


def test_models_url_never_duplicates_v1() -> None:
    assert models_url("https://api.example.com/v1", "/models") == (
        "https://api.example.com/v1/models"
    )
    assert models_url("https://api.example.com/v1", "/v1/models") == (
        "https://api.example.com/v1/models"
    )


def test_normalize_common_model_list_shapes() -> None:
    expected = [{"id": "a"}, {"id": "b"}]
    assert normalize_models({"data": [{"id": "b"}, {"id": "a"}]}) == expected
    assert normalize_models({"models": [{"id": "a"}, {"id": "b"}]}) == expected
    assert normalize_models({"models": ["b", "a"]}) == expected
    assert normalize_models([{"name": "b"}, {"id": "a"}]) == expected
    assert normalize_models({"unexpected": []}) == []


def _reset_server(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    server._resolver = None


def test_custom_provider_crud_test_discover_refresh_and_delete(tmp_path: Path, monkeypatch) -> None:
    _reset_server(tmp_path, monkeypatch)
    secret = "AI_TEAM_OS_TEST_CUSTOM_PROVIDER"
    body = {
        "provider_name": "M4 Isolated Provider",
        "base_url": "https://third-party-test.invalid/v1",
        "models_endpoint": "/models",
        "chat_endpoint": "/chat/completions",
        "api_mode": "openai_compatible",
        "default_model": "m4-test-small",
        "role_models": {"reviewer": "m4-test-reasoning"},
        "is_default": True,
        "test_provider": True,
    }
    with TestClient(app) as client:
        created = client.post("/settings/connections/providers", json=body)
        assert created.status_code == 200
        provider_id = created.json()["provider_id"]
        credential = client.put(
            f"/settings/connections/providers/{provider_id}/credential",
            json={"api_key": secret, "storage_mode": "session"},
        )
        assert credential.json() == {
            "provider_id": provider_id,
            "configured": True,
            "storage": "session",
        }
        tested = client.post(f"/settings/connections/providers/{provider_id}/test")
        assert tested.json()["status"] == "healthy"
        discovered = client.post(f"/settings/connections/providers/{provider_id}/discover-models")
        assert discovered.status_code == 200
        assert discovered.json()["count"] == 3
        assert discovered.json()["models"][0]["id"] == "m4-test-pro"
        refreshed = client.post(f"/settings/connections/providers/{provider_id}/refresh-models")
        assert refreshed.json()["count"] == 3
        listed = client.get("/settings/connections/providers").json()["providers"]
        assert listed[0]["model_count"] == 3
        assert listed[0]["configured"] is True
        serialized = str(listed) + str(discovered.json())
        assert secret not in serialized
        assert (
            client.delete(f"/settings/connections/providers/{provider_id}/credential").json()[
                "configured"
            ]
            is False
        )
        assert (
            client.delete(f"/settings/connections/providers/{provider_id}").json()["deleted"]
            is True
        )

    db = tmp_path / "data" / "runtime" / "providers.sqlite"
    assert secret.encode() not in db.read_bytes()


def test_ssrf_blocks_loopback_and_private_by_default(tmp_path: Path, monkeypatch) -> None:
    _reset_server(tmp_path, monkeypatch)
    with TestClient(app) as client:
        for url in (
            "http://127.0.0.1:8000/v1",
            "http://10.0.0.7/v1",
            "http://169.254.169.254/latest",
        ):
            response = client.post(
                "/settings/connections/providers",
                json={"provider_name": url, "base_url": url},
            )
            assert response.status_code == 400


def test_explicit_local_provider_allows_loopback(tmp_path: Path, monkeypatch) -> None:
    _reset_server(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/settings/connections/providers",
            json={
                "provider_name": "Local Gateway",
                "base_url": "http://127.0.0.1:8000/v1",
                "local_provider": True,
            },
        )
        assert response.status_code == 200
        public_http = client.post(
            "/settings/connections/providers",
            json={
                "provider_name": "Unsafe public HTTP",
                "base_url": "http://8.8.8.8/v1",
                "local_provider": True,
            },
        )
        assert public_http.status_code == 400


def test_provider_store_supports_multiple_and_one_default(tmp_path: Path) -> None:
    store = ProviderStore(tmp_path / "providers.sqlite")
    one = store.create(provider_name="one", base_url="https://one.example", is_default=True)
    two = store.create(provider_name="two", base_url="https://two.example", is_default=True)
    assert store.default().provider_id == two.provider_id  # type: ignore[union-attr]
    assert store.get(one.provider_id).is_default is False  # type: ignore[union-attr]


def test_default_custom_provider_supplies_role_routes_and_runtime(tmp_path: Path) -> None:
    from app.core.config import load_settings

    data_dir = tmp_path / "data"
    store = ProviderStore(data_dir / "runtime" / "providers.sqlite")
    provider = store.create(
        provider_name="runtime",
        base_url="https://8.8.8.8/v1",
        default_model="model-default",
        role_models={"reviewer": "model-reviewer"},
        discovered_models=[{"id": "model-default"}, {"id": "model-reviewer"}],
        is_default=True,
    )
    process_resolver(data_dir).set(store.secret_key(provider.provider_id), "runtime-secret")
    settings = _settings_with_custom_routes(load_settings({}), data_dir)
    router = build_router(settings)
    assert router.resolve("planner") == "model-default"
    assert router.resolve("reviewer") == "model-reviewer"
    runtime = build_provider(settings, data_dir)
    assert runtime.health_check().status == "healthy"


class _FakeHttpClient:
    response: object

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def get(self, *args, **kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def stream(self, *args, **kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _Response:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def iter_bytes(self):
        yield json.dumps(self._payload).encode()


@pytest.mark.parametrize(
    ("response", "expected_status", "expected_api_status"),
    [
        (_Response(404), "unsupported", 200),
        (_Response(401), None, 401),
        (_Response(429), None, 429),
        (_Response(200, {"wrong": "shape"}), "unsupported_response", 200),
        (_Response(200, {"models": ["x" * (1024 * 1024)]}), None, 502),
        (httpx.ReadTimeout("slow"), None, 504),
    ],
)
def test_model_discovery_safe_error_mapping(
    tmp_path: Path,
    monkeypatch,
    response,
    expected_status: str | None,
    expected_api_status: int,
) -> None:
    _reset_server(tmp_path, monkeypatch)
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    _FakeHttpClient.response = response
    with TestClient(app) as client:
        provider = client.post(
            "/settings/connections/providers",
            json={"provider_name": "remote", "base_url": "https://8.8.8.8/v1"},
        ).json()
        client.put(
            f"/settings/connections/providers/{provider['provider_id']}/credential",
            json={"api_key": "AI_TEAM_OS_TEST_CUSTOM_CREDENTIAL", "storage_mode": "session"},
        )
        result = client.post(
            f"/settings/connections/providers/{provider['provider_id']}/discover-models"
        )
        assert result.status_code == expected_api_status
        if expected_status:
            assert result.json()["status"] == expected_status
