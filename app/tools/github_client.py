"""GitHub 只读客户端（006 六）：仅 GET，Token 只从环境变量，401/403/404/429 分类。

安全（6.1/6.2/6.3）：
- 仅 GET 请求；不提供 GraphQL mutation；不提供写接口。
- Token 可选，只从环境变量 AI_TEAM_GITHUB_TOKEN 读取；不进状态/日志/Evidence。
- 无 Token 允许公开仓库（限流处理）；429 分类明确。
- 仓库标识校验：接受 owner/repo 或 https://github.com/owner/repo；拒绝非 GitHub 域名、
  路径穿越、任意 API Base URL。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

GITHUB_API_BASE = "https://api.github.com"
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,39}$")
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class GitHubToolError(Exception):
    """GitHub 工具错误（安全消息，不含原始响应）。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code  # not_found | forbidden | rate_limited | auth_error | network | invalid
        self.message = message
        super().__init__(message)


def validate_repo_identifier(value: str) -> str:
    """规范化仓库标识（6.3）：接受 owner/repo 或 https://github.com/owner/repo。

    拒绝：非 GitHub 域名、路径穿越（..）、URL 路径带多余段、任意 API Base URL。
    """
    stripped = value.strip()
    if stripped.startswith("https://github.com/"):
        rest = stripped[len("https://github.com/") :].rstrip("/")
        parts = rest.split("/")
        if len(parts) < 2:
            raise GitHubToolError("invalid", "invalid github repo url")
        owner, repo = parts[0], parts[1]
        if ".." in owner or ".." in repo:
            raise GitHubToolError("invalid", "path traversal rejected")
        return f"{owner}/{repo}"
    if stripped.startswith("http://") or stripped.startswith("https://"):
        # 其他 URL（非 github.com）→ 拒绝（6.3：非 GitHub 域名冒充）
        raise GitHubToolError("invalid", "only github.com urls or owner/repo are accepted")
    if ".." in stripped:
        raise GitHubToolError("invalid", "path traversal rejected")
    if not _REPO_RE.match(stripped):
        raise GitHubToolError("invalid", "repo must match owner/repo")
    return stripped


def validate_file_path(path: str) -> str:
    """文件路径校验：拒绝绝对路径、穿越、反斜杠（Windows 逃逸）。"""
    if not path:
        raise GitHubToolError("invalid", "path is empty")
    if path.startswith("/") or path.startswith("\\"):
        raise GitHubToolError("invalid", "absolute path rejected")
    parts = path.replace("\\", "/").split("/")
    if any(p == ".." for p in parts):
        raise GitHubToolError("invalid", "path traversal rejected")
    if any(not p for p in parts):
        raise GitHubToolError("invalid", "malformed path")
    return "/".join(parts)


def validate_query(value: str, max_len: int = 200) -> str:
    if not value.strip():
        raise GitHubToolError("invalid", "query is empty")
    if len(value) > max_len:
        raise GitHubToolError("invalid", "query too long")
    return value.strip()


@dataclass
class GitHubClient:
    """仅 GET 的 GitHub API 客户端（mock transport 可注入）。"""

    token: str = field(default_factory=lambda: os.environ.get("AI_TEAM_GITHUB_TOKEN", ""))
    timeout_seconds: int = 30
    transport: httpx.BaseTransport | None = None
    max_response_bytes: int = _MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ai-team-os/0.4.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        self._headers = headers
        self._client = httpx.Client(
            base_url=GITHUB_API_BASE,
            timeout=self.timeout_seconds,
            follow_redirects=False,
            headers=headers,
            transport=self.transport,
        )
        self.request_count = 0

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """仅 GET（6.1）。路径必须为内部构造的 API 路径；响应可为 dict 或 list。"""
        if path.startswith("http"):
            raise GitHubToolError("invalid", "absolute api url rejected")
        self.request_count += 1
        try:
            resp = self._client.get(f"/{path.lstrip('/')}", params=params or {})
        except httpx.TimeoutException as exc:
            raise GitHubToolError("network", "github api timed out") from exc
        except httpx.HTTPError as exc:
            raise GitHubToolError("network", "github api connection failed") from exc
        if len(resp.content) > self.max_response_bytes:
            raise GitHubToolError("network", "github api response too large")
        if resp.status_code == 401:
            raise GitHubToolError("auth_error", "github token invalid or missing")
        if resp.status_code == 403:
            if resp.headers.get("x-ratelimit-remaining") == "0":
                raise GitHubToolError("rate_limited", "github rate limit exceeded")
            raise GitHubToolError("forbidden", "github access forbidden")
        if resp.status_code == 404:
            raise GitHubToolError("not_found", "github resource not found")
        if resp.status_code == 429:
            raise GitHubToolError("rate_limited", "github rate limit exceeded")
        if resp.status_code != 200:
            raise GitHubToolError("network", f"github api status {resp.status_code}")
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise GitHubToolError("network", "github api returned non-JSON") from exc

    def close(self) -> None:
        self._client.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summarize(data: dict[str, Any]) -> str:
    """摘要素材（Evidence summary 用），脱敏由 EvidenceWriter 执行。"""
    return json.dumps(data, ensure_ascii=False, default=str)[:300]
