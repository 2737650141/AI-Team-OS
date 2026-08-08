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
    yield
    srv._resolver = None


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
    resolver.set("openai_compatible.api_key", "session-key", "session")
    assert resolver.resolve("openai_compatible.api_key", ["AI_TEAM_MODEL_API_KEY"]) == "session-key"
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
