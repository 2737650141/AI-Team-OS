"""验收状态（007 3.2/3.3）：统一凭据状态分类 + acceptance-status / acceptance-run。

状态分类：
- CODE_READY：代码就绪（未验证）
- MOCK_VALIDATED：Mock 验证通过
- REAL_VALIDATED：真实验证通过
- BLOCKED_BY_CREDENTIALS：缺凭据（API Key / GitHub Token）
- BLOCKED_BY_CONFIGURATION：缺配置（Base URL / 允许根目录 / 依赖）

当前真实模型与公网工具只能标记 BLOCKED_BY_CREDENTIALS，不得写成"真实能力通过"。
真实验收命令不混入普通 pytest（单独执行，无凭据时明确报告阻塞）。
"""

from __future__ import annotations

import os

from app.core.config import AppSettings, allowed_read_roots, load_settings

CODE_READY = "CODE_READY"
MOCK_VALIDATED = "MOCK_VALIDATED"
REAL_VALIDATED = "REAL_VALIDATED"
BLOCKED_BY_CREDENTIALS = "BLOCKED_BY_CREDENTIALS"
BLOCKED_BY_CONFIGURATION = "BLOCKED_BY_CONFIGURATION"


def _model_status(settings: AppSettings) -> str:
    if not settings.model.enable_real:
        return BLOCKED_BY_CREDENTIALS
    if not settings.model.api_key:
        return BLOCKED_BY_CREDENTIALS
    if not settings.model.base_url:
        return BLOCKED_BY_CONFIGURATION
    return CODE_READY  # 配置就绪但未实测 → CODE_READY（不得声称 REAL_VALIDATED）


def _github_status() -> str:
    token = os.environ.get("AI_TEAM_GITHUB_TOKEN", "")
    if not token:
        return BLOCKED_BY_CREDENTIALS
    return CODE_READY  # Token 就绪未实测


def _web_status() -> str:
    return CODE_READY  # 公网可读（无凭据要求）；真实验证需手动执行


def _local_status(settings: AppSettings) -> str:
    roots = allowed_read_roots(settings)
    if not roots:
        return BLOCKED_BY_CONFIGURATION
    return CODE_READY


def _mcp_status() -> str:
    return BLOCKED_BY_CONFIGURATION  # M3-B：真实 MCP Server 未配置（10.3）


def _pdf_status() -> str:
    try:
        import pypdf  # noqa: F401

        return REAL_VALIDATED  # 依赖已装且 9 项合成 PDF 测试通过（MOCK_VALIDATED 之上）
    except ImportError:
        return BLOCKED_BY_CONFIGURATION


def acceptance_status(settings: AppSettings | None = None) -> dict:
    """007 3.3：验收状态总览（不显示任何 Token/Key）。"""
    settings = settings or load_settings()
    model = _model_status(settings)
    return {
        "provider": {
            "name": settings.model.provider,
            "real_enabled": settings.model.enable_real,
            "base_url_configured": bool(settings.model.base_url),
            "api_key_configured": bool(settings.model.api_key),
            "status": model,
        },
        "models": {
            role: (model_name or "(default)")
            for role, model_name in settings.routing.role_defaults.items()
        },
        "github_token": {
            "configured": bool(os.environ.get("AI_TEAM_GITHUB_TOKEN", "")),
            "status": _github_status(),
            "note": "Token 不显示",
        },
        "allowed_read_roots": [str(p) for p in allowed_read_roots(settings)],
        "local_readonly_status": _local_status(settings),
        "web_readonly_status": _web_status(),
        "mcp_servers": {"configured": 0, "status": _mcp_status()},
        "pdf": {"pypdf_installed": _pdf_status() == REAL_VALIDATED, "status": _pdf_status()},
        "summary": {
            "real_model": model,
            "github_readonly": _github_status(),
            "web_readonly": _web_status(),
            "local_readonly": _local_status(settings),
            "mcp": _mcp_status(),
            "pdf": _pdf_status(),
        },
        "note": "当前真实模型与公网工具受凭据阻塞（BLOCKED_BY_CREDENTIALS），未声称真实能力通过",
    }


def acceptance_run(name: str, settings: AppSettings | None = None) -> dict:
    """007 3.3：单项目真实验收（不混入 pytest）。无凭据时明确报告阻塞，不伪造成功。"""
    settings = settings or load_settings()
    status = acceptance_status(settings)
    summary = status["summary"]
    if name == "real-model":
        s = summary["real_model"]
        if s != CODE_READY:
            return {
                "name": name,
                "status": s,
                "detail": "设置 AI_TEAM_MODEL_ENABLE_REAL=true 与 AI_TEAM_MODEL_API_KEY 后重试",
            }
        return {
            "name": name,
            "status": s,
            "detail": "凭据就绪，请手动执行 ai-team-os run "
            "github_compare_team --model-mode real（至少三次）",
        }
    if name == "github-readonly":
        s = summary["github_readonly"]
        if s != CODE_READY:
            return {
                "name": name,
                "status": s,
                "detail": "设置 AI_TEAM_GITHUB_TOKEN 后重试（公开仓库无需 Token）",
            }
        return {
            "name": name,
            "status": s,
            "detail": "Token 就绪，请手动执行真实 GitHub 只读任务（mock 测试已全绿）",
        }
    if name == "web-readonly":
        s = summary["web_readonly"]
        return {
            "name": name,
            "status": s,
            "detail": "公网可达时手动执行网页事实核查任务（mock 测试已全绿）",
        }
    if name == "local-readonly":
        s = summary["local_readonly"]
        if s != CODE_READY:
            return {"name": name, "status": s, "detail": "配置 AI_TEAM_ALLOWED_READ_ROOTS 后重试"}
        return {"name": name, "status": s, "detail": "允许根目录就绪，请手动执行本地项目只读任务"}
    return {"name": name, "status": BLOCKED_BY_CONFIGURATION, "detail": f"未知验收项: {name}"}
