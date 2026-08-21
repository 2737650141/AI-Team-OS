"""Secret Store / Connections API 测试（010 四十九 / 009-A 二十二）。

覆盖：
- SessionSecretStore 不落盘、重启失效。
- SecretResolver 优先级 Session > Secure > ENV；环境变量向后兼容。
- WindowsSecretStore round-trip（Windows 平台；非 Windows skip）。
- GET /settings/connections 不返回 Secret。
- PUT 保存不回显；DELETE 后 configured=false。
- Test Connection 无凭据 → authentication_failed（不发网络）。
- Base URL SSRF：localhost 拒绝（非本地 Provider）；Ollama 本地放行。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.core.secret_store import SecretResolver, SessionSecretStore, WindowsSecretStore

FAKE_KEY = "sk-" + "s" * 30


@pytest.fixture(autouse=True)
def _reset_resolver():
    """测试间重置 server 级 resolver（避免跨测试残留）。"""
    import app.api.server as srv

    srv._resolver = None
    srv._CONNECTION_HEALTH.clear()
    yield
    srv._resolver = None
    srv._CONNECTION_HEALTH.clear()


def test_session_store_not_persisted(tmp_path: Path) -> None:
    """SessionSecretStore：不落盘、新实例无值（重启失效）。"""
    s1 = SessionSecretStore()
    s1.set_secret("openai_compatible.api_key", FAKE_KEY)
    assert s1.get_secret("openai_compatible.api_key") == FAKE_KEY
    s2 = SessionSecretStore()  # 模拟后端重启
    assert s2.get_secret("openai_compatible.api_key") is None
    assert not list(tmp_path.rglob("*.bin"))


def test_resolver_priority_session_over_env(monkeypatch) -> None:
    """SecretResolver：Session > Secure > ENV。"""
    monkeypatch.setenv("AI_TEAM_MODEL_API_KEY", "env-key")
    resolver = SecretResolver(session=SessionSecretStore())
    session_value = "AI_TEAM_OS_TEST_SESSION_VALUE"
    resolver.set("openai_compatible.api_key", session_value, "session")
    assert resolver.resolve("openai_compatible.api_key", ["AI_TEAM_MODEL_API_KEY"]) == session_value
    assert resolver.store_mode("openai_compatible.api_key") == "session"
    resolver.delete("openai_compatible.api_key")
    # 删除后回退环境变量
    assert resolver.resolve("openai_compatible.api_key", ["AI_TEAM_MODEL_API_KEY"]) == "env-key"
    assert resolver.store_mode("openai_compatible.api_key") == "environment_variable"


def test_resolver_env_fallback(monkeypatch) -> None:
    """环境变量向后兼容（010 二十八 Advanced/Deployment mode）。"""
    monkeypatch.setenv("AI_TEAM_GITHUB_TOKEN", "ghp_testtoken")
    resolver = SecretResolver(session=SessionSecretStore())
    assert resolver.resolve("github.token", ["AI_TEAM_GITHUB_TOKEN"]) == "ghp_testtoken"


@pytest.mark.skipif(sys.platform == "win32" and os.name != "nt", reason="requires Windows")
def test_windows_store_roundtrip(tmp_path: Path) -> None:
    """WindowsSecretStore round-trip（Windows DPAPI；非 Windows skip）。"""
    if os.name != "nt":
        pytest.skip("WindowsSecretStore requires Windows")
    store = WindowsSecretStore(tmp_path)
    store.set_secret("github.token", "ghp_testtoken12345")
    assert store.get_secret("github.token") == "ghp_testtoken12345"
    assert store.has_secret("github.token")
    store.delete_secret("github.token")
    assert not store.has_secret("github.token")


def test_connections_status_no_secret(tmp_path: Path, monkeypatch) -> None:
    """GET /settings/connections：不含任何 Secret 值/片段。"""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        resp = client.get("/settings/connections")
        assert resp.status_code == 200
        body = resp.json()
        text = str(body)
        assert "openai_compatible" in body and "github" in body and "ollama" in body
        for k in ("api_key", "token", "secret", "authorization", "last4", "prefix", "suffix"):
            assert k not in text


def test_put_delete_connection(tmp_path: Path, monkeypatch) -> None:
    """PUT 保存（不回显 Secret）→ DELETE 后 configured=false。"""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        resp = client.put(
            "/settings/connections/openai_compatible",
            json={"base_url": "https://8.8.8.8/v1", "api_key": FAKE_KEY, "storage_mode": "session"},
        )
        assert resp.status_code == 200
        assert FAKE_KEY not in str(resp.json())
        assert resp.json()["configured"] is True
        # 状态只显示 configured + storage，不返回密钥
        st = client.get("/settings/connections").json()["openai_compatible"]
        assert st["configured"] is True and st["storage"] == "session"
        assert FAKE_KEY not in str(st)
        # DELETE
        resp2 = client.delete("/settings/connections/openai_compatible/credential")
        assert resp2.status_code == 200
        assert resp2.json()["configured"] is False
        st2 = client.get("/settings/connections").json()["openai_compatible"]
        assert st2["configured"] is False


def test_test_connection_without_credential(tmp_path: Path, monkeypatch) -> None:
    """Test Connection 无凭据 → authentication_failed（不发网络）。"""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        resp = client.post("/settings/connections/openai_compatible/test")
        assert resp.status_code == 200
        assert resp.json()["status"] == "authentication_failed"


def test_base_url_ssrf_localhost_rejected(tmp_path: Path, monkeypatch) -> None:
    """SSRF：非本地 Provider 拒绝 localhost（010 三十六）。"""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        resp = client.put(
            "/settings/connections/openai_compatible",
            json={
                "base_url": "http://127.0.0.1:8000",
                "api_key": FAKE_KEY,
                "storage_mode": "session",
            },
        )
        assert resp.status_code == 400
        assert "localhost" in resp.json()["detail"]
        # 非 http 也拒绝
        resp2 = client.put(
            "/settings/connections/openai_compatible",
            json={"base_url": "file:///etc/passwd", "api_key": FAKE_KEY, "storage_mode": "session"},
        )
        assert resp2.status_code == 400


def test_ollama_local_provider_allowed(tmp_path: Path, monkeypatch) -> None:
    """Ollama 本地 Provider：http://127.0.0.1:11434 放行。"""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        resp = client.put(
            "/settings/connections/ollama",
            json={"base_url": "http://127.0.0.1:11434", "local_provider": True},
        )
        assert resp.status_code == 200
        st = client.get("/settings/connections").json()["ollama"]
        assert st["configured"] is True and st["local_provider"] is True
        # 测试连接（本地 provider 无凭据 → healthy）
        t = client.post("/settings/connections/ollama/test")
        assert t.json()["status"] == "healthy"


def test_isolated_test_provider_full_lifecycle(tmp_path: Path, monkeypatch) -> None:
    """Test Provider: save → test → discover → replace → remove, without network access."""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    first_key = "test-only-first-key"
    second_key = "test-only-replacement-key"
    with TestClient(app) as client:
        saved = client.put(
            "/settings/connections/test_provider",
            json={
                "api_key": first_key,
                "storage_mode": "session",
                "models": {"default": "jarvis-test-small"},
            },
        )
        assert saved.status_code == 200 and saved.json()["configured"] is True
        assert first_key not in str(saved.json())
        assert client.post("/settings/connections/test_provider/test").json()["status"] == "healthy"
        models = client.get("/settings/connections/test_provider/models").json()
        assert models["supported"] is True
        assert "jarvis-test-pro" in models["models"]

        replaced = client.put(
            "/settings/connections/test_provider",
            json={"api_key": second_key, "storage_mode": "session"},
        )
        assert replaced.status_code == 200
        assert first_key not in str(client.get("/settings/connections").json())
        assert second_key not in str(client.get("/settings/connections").json())
        assert client.delete(
            "/settings/connections/test_provider/credential"
        ).json()["configured"] is False


def test_github_test_provider_does_not_touch_real_github_credential(
    tmp_path: Path, monkeypatch
) -> None:
    """GitHub Test uses a separate SecretStore key from the user's real GitHub connection."""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        client.put(
            "/settings/connections/github",
            json={"api_key": "real-placeholder", "storage_mode": "session"},
        )
        client.put(
            "/settings/connections/github_test",
            json={"api_key": "test-placeholder", "storage_mode": "session"},
        )
        assert client.post("/settings/connections/github_test/test").json()["status"] == "healthy"
        client.delete("/settings/connections/github_test/credential")
        status = client.get("/settings/connections").json()
        assert status["github_test"]["configured"] is False
        assert status["github"]["configured"] is True


# ---------- 010-B：网页保存凭据驱动真实模式（build_provider 回退 + real 校验） ----------
def test_web_saved_credentials_drive_real_provider(tmp_path: Path) -> None:
    """网页保存的 openai_compatible 凭据对真实任务生效（build_provider 回退）。"""
    from app.core.config import AppSettings
    from app.core.secret_store import default_resolver
    from app.runner import _web_configured_credentials, build_provider

    data_dir = tmp_path / "data"
    resolver = default_resolver(data_dir)
    resolver.set("openai_compatible.base_url", "https://8.8.8.8/v1", "secure")
    resolver.set("openai_compatible.api_key", "AI_TEAM_OS_TEST_sk-PLACEHOLDER-CONNECTIONS", "secure")
    resolver.set("openai_compatible.default_model", "web-model", "secure")

    settings = AppSettings()  # env 未配置（enable_real=False）
    url, key, model = _web_configured_credentials(settings, data_dir)
    assert url == "https://8.8.8.8/v1"
    assert key == "AI_TEAM_OS_TEST_sk-PLACEHOLDER-CONNECTIONS"
    assert model == "web-model"

    provider = build_provider(settings, data_dir)
    from app.gateway.openai_compatible import OpenAICompatibleProvider

    assert isinstance(provider, OpenAICompatibleProvider)
    # enable_real 仍为 False（未显式开启）→ provider 拒绝调用；凭据回退不改变开关语义
    assert provider._enable_real is False


def test_web_saved_credentials_satisfy_real_gate(tmp_path: Path, monkeypatch) -> None:
    """runner：网页已保存凭据时，real 模式校验通过（无需 env 开关）。"""
    import app.core.events as _evmod
    from app.core.config import AppSettings
    from app.core.secret_store import default_resolver
    from app.runner import _build_context

    _evmod._store = None
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    from app.core.state import TaskState

    data_dir = tmp_path / "data"
    resolver = default_resolver(data_dir)
    resolver.set("openai_compatible.base_url", "https://8.8.8.8/v1", "secure")
    resolver.set("openai_compatible.api_key", "AI_TEAM_OS_TEST_sk-PLACEHOLDER-CONNECTIONS", "secure")

    state = TaskState(
        task_id="t1",
        run_id="r1",
        goal="g",
        user_goal="g",
        model_mode="real",
        token_budget=1000,
        cost_budget=0.1,
    )
    ctx = _build_context(state, data_dir, settings=AppSettings(), model_mode="real")
    assert ctx.provider is not None  # 校验通过（未抛 ProviderError）

    # 未保存凭据且未开启开关 → 仍拒绝（005 7.4 兼容）
    import pytest

    from app.gateway.contracts import ProviderError

    monkeypatch.delenv("AI_TEAM_OS_DATA_DIR", raising=False)
    empty_dir = tmp_path / "empty"
    with pytest.raises(ProviderError):
        _build_context(
            TaskState(
                task_id="t2",
                run_id="r2",
                goal="g",
                user_goal="g",
                model_mode="real",
                token_budget=1000,
                cost_budget=0.1,
            ),
            empty_dir,
            settings=AppSettings(),
            model_mode="real",
        )
