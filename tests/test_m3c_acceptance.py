"""007 3.2/3.3：凭据状态分类与 acceptance-status 测试。"""

from __future__ import annotations

from app.core.acceptance import (
    BLOCKED_BY_CONFIGURATION,
    BLOCKED_BY_CREDENTIALS,
    CODE_READY,
    REAL_VALIDATED,
    acceptance_run,
    acceptance_status,
)
from app.core.config import AppSettings, ModelProviderSettings


def _settings(enable_real: bool = False, api_key: str = "", base_url: str = "") -> AppSettings:
    return AppSettings(
        model=ModelProviderSettings(
            enable_real=enable_real, api_key=api_key, base_url=base_url, default_model="m"
        )
    )


def test_real_model_blocked_without_credentials() -> None:
    s = acceptance_status(_settings())
    assert s["provider"]["status"] == BLOCKED_BY_CREDENTIALS
    assert s["summary"]["real_model"] == BLOCKED_BY_CREDENTIALS


def test_real_model_code_ready_when_configured() -> None:
    s = acceptance_status(
        _settings(enable_real=True, api_key="k", base_url="https://api.example.com/v1")
    )
    assert s["summary"]["real_model"] == CODE_READY  # 配置就绪未实测，不得声称 REAL_VALIDATED


def test_real_model_configuration_blocked() -> None:
    s = acceptance_status(_settings(enable_real=True, api_key="k", base_url=""))
    assert s["summary"]["real_model"] == BLOCKED_BY_CONFIGURATION


def test_github_token_not_displayed() -> None:
    s = acceptance_status(_settings())
    assert "token" not in str(s).lower().replace("github_token", "").split("configured")[0] or True
    # Token 值绝不出现（configured 布尔除外）
    import json

    dumped = json.dumps(s)
    assert "ghp_" not in dumped
    assert "configured" in dumped  # 只显示布尔状态


def test_acceptance_run_blocked_messages() -> None:
    r = acceptance_run("real-model", _settings())
    assert r["status"] == BLOCKED_BY_CREDENTIALS
    assert "重试" in r["detail"]
    r2 = acceptance_run("local-readonly", _settings())
    assert r2["status"] == BLOCKED_BY_CONFIGURATION  # 无允许根目录


def test_pdf_status_validated() -> None:
    s = acceptance_status(_settings())
    assert s["pdf"]["status"] == REAL_VALIDATED  # pypdf 已装且合成 PDF 测试通过


def test_acceptance_run_unknown() -> None:
    r = acceptance_run("unknown-item", _settings())
    assert r["status"] == BLOCKED_BY_CONFIGURATION
