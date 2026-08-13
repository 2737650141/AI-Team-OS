"""Acceptance Runtime = Production Provider Runtime（020-B 二/三）。

验收脚本不得维护第二套 Provider 配置逻辑，也不得以"没有 AI_TEAM_MODEL_* 环境变量"
为由回退 Fake。统一走生产链路：

    SecretResolver → Windows Secure Store → ProviderStore → build_provider

本模块只封装"生产链路探测/决策"，不含任何密钥、不落盘 Key；
凭据获取完全复用 app.core.secret_store / app.gateway / app.runner。
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import AppSettings
from app.gateway.fake_provider import FakeModelProvider
from app.runner import (
    _default_custom_provider,
    _settings_with_custom_routes,
    _team_route_has_runtime,
    _web_configured_credentials,
    build_provider,
)

WAITING_FOR_USER_CREDENTIAL_INPUT = "WAITING_FOR_USER_CREDENTIAL_INPUT"


def production_provider_status(data_dir: Path | None = None) -> dict:
    """生产 Provider Runtime 状态探测（复用 build_provider，不复制配置逻辑）。

    返回：
      {"available": True, "provider_name": "...", "model": "...", "source": "..."}
      或 {"available": False, "reason": "no_real_provider_configured",
          "hint": "请到 App: Settings → Connections 录入凭据（不得自动回退 Fake）"}
    """
    data_dir = data_dir or Path("data")
    settings = _settings_with_custom_routes(AppSettings(), data_dir)
    provider = build_provider(settings, data_dir)
    if isinstance(provider, FakeModelProvider):
        return {
            "available": False,
            "reason": "no_real_provider_configured",
            "hint": (
                "本机 Windows Secure Store / Connections 未配置可用 Provider。"
                "请到 App: Settings → Connections 录入（如 DeepSeek Official），"
                "本验收不得自动回退 Fake。"
            ),
        }
    return {
        "available": True,
        "provider_name": getattr(provider, "provider_name", None)
        or type(provider).__name__,
        "model": getattr(provider, "default_model", None) or "",
        "source": _provider_source(data_dir),
    }


def _provider_source(data_dir: Path) -> str:
    """凭据来源标识（仅诊断用途，不含密钥）。"""
    from app.core.secret_store import process_resolver

    resolver = process_resolver(data_dir)
    sources = []
    if resolver.resolve("openai_compatible.api_key"):
        sources.append("openai_compatible")
    if resolver.resolve("github.token"):
        sources.append("github")
    _, custom_key = _default_custom_provider(data_dir)
    if custom_key:
        sources.append("custom_provider")
    if _team_route_has_runtime(data_dir):
        sources.append("team_routing")
    _, web_key, _ = _web_configured_credentials(AppSettings(), data_dir)
    if web_key:
        sources.append("web_configured")
    return ",".join(sources) or "unknown"


def effective_model_mode(
    requested: str | None, data_dir: Path | None = None
) -> tuple[str, dict]:
    """验收脚本的 model_mode 决策：

    - requested == "real" → 强制真实（无凭据返回 WAITING_FOR_USER_CREDENTIAL_INPUT）
    - requested in (None, "auto") → 有生产 Provider 用 real；无则 WAITING（不降级 Fake）
    - requested == "fake" → 显式 fake（仅离线基线，报告中必须标注）
    """
    status = production_provider_status(data_dir)
    if requested == "real" or requested in (None, "auto"):
        if status["available"]:
            return "real", status
        return WAITING_FOR_USER_CREDENTIAL_INPUT, status
    return "fake", status
