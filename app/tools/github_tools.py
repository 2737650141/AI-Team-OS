"""GitHub 只读工具（006 六）：10 个工具，全部 risk_level=safe / read_only=true。

全部经 Tool Gateway 调用；仅 GET；Token 由 GitHubClient 私有持有；
结果由网关固化 Evidence（source_type=github）。
"""

from __future__ import annotations

from typing import Any

from app.tools.github_client import (
    GitHubClient,
    GitHubToolError,
    validate_file_path,
    validate_query,
    validate_repo_identifier,
)
from app.tools.spec import RiskLevel, ToolSpec


def _spec(name: str, description: str, schema: dict[str, Any], handler) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        input_schema=schema,
        risk_level=RiskLevel.SAFE,
        read_only=True,
        handler=handler,
        roles=("researcher",),
    )


def build_github_tools(client: GitHubClient) -> list[ToolSpec]:
    """构造 GitHub 只读工具集（共享同一 client，mock transport 可注入）。"""

    def _err(exc: GitHubToolError) -> dict:
        # 安全消息：不含原始响应；分类到 ProviderError 兼容语义
        return {"ok": False, "error": exc.message, "code": exc.code}

    def repo_info(repo: str) -> dict:
        try:
            repo_id = validate_repo_identifier(repo)
            data = client.get(f"repos/{repo_id}")
            return {
                "ok": True,
                "full_name": data.get("full_name"),
                "description": data.get("description"),
                "license": (data.get("license") or {}).get("spdx_id"),
                "stars": data.get("stargazers_count"),
                "forks": data.get("forks_count"),
                "open_issues": data.get("open_issues_count"),
                "default_branch": data.get("default_branch"),
                "pushed_at": data.get("pushed_at"),
                "archived": data.get("archived"),
                "html_url": data.get("html_url"),
                "url": f"https://github.com/{repo_id}",
            }
        except GitHubToolError as exc:
            return _err(exc)

    def read_file(repo: str, path: str) -> dict:
        try:
            repo_id = validate_repo_identifier(repo)
            safe_path = validate_file_path(path)
            data = client.get(f"repos/{repo_id}/contents/{safe_path}")
            if isinstance(data, list):
                return {"ok": False, "error": "path is a directory", "code": "invalid"}
            import base64

            content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            return {
                "ok": True,
                "path": safe_path,
                "size": data.get("size"),
                "encoding": data.get("encoding"),
                "content": content[:20000],
                "url": data.get("html_url"),
            }
        except GitHubToolError as exc:
            return _err(exc)

    def list_directory(repo: str, path: str = "") -> dict:
        try:
            repo_id = validate_repo_identifier(repo)
            safe_path = validate_file_path(path) if path else ""
            data = client.get(
                f"repos/{repo_id}/contents/{safe_path}"
                if safe_path
                else f"repos/{repo_id}/contents"
            )
            if isinstance(data, dict) and "content" in data:
                return {"ok": False, "error": "path is a file", "code": "invalid"}
            entries = [
                {"name": e.get("name"), "type": e.get("type"), "size": e.get("size")}
                for e in data
                if isinstance(e, dict)
            ]
            return {"ok": True, "path": safe_path or "/", "entries": entries[:500]}
        except GitHubToolError as exc:
            return _err(exc)

    def list_commits(repo: str, per_page: int = 10) -> dict:
        try:
            repo_id = validate_repo_identifier(repo)
            per = max(1, min(per_page, 100))
            data = client.get(f"repos/{repo_id}/commits", params={"per_page": per})
            commits = [
                {
                    "sha": c.get("sha", "")[:12],
                    "date": (c.get("commit") or {}).get("author", {}).get("date"),
                    "message": ((c.get("commit") or {}).get("message") or "").splitlines()[0][:200],
                    "author": ((c.get("commit") or {}).get("author") or {}).get("name"),
                }
                for c in data
                if isinstance(c, dict)
            ]
            return {"ok": True, "count": len(commits), "commits": commits}
        except GitHubToolError as exc:
            return _err(exc)

    def _issue_summary(item: dict) -> dict:
        return {
            "number": item.get("number"),
            "title": item.get("title"),
            "state": item.get("state"),
            "created_at": item.get("created_at"),
            "labels": [
                label.get("name") for label in (item.get("labels") or []) if isinstance(label, dict)
            ],
            "is_pr": "pull_request" in item,
        }

    def list_issues(repo: str, state: str = "open", per_page: int = 10) -> dict:
        try:
            repo_id = validate_repo_identifier(repo)
            if state not in ("open", "closed", "all"):
                return {"ok": False, "error": "state must be open|closed|all", "code": "invalid"}
            per = max(1, min(per_page, 100))
            data = client.get(f"repos/{repo_id}/issues", params={"state": state, "per_page": per})
            issues = [
                _issue_summary(i) for i in data if isinstance(i, dict) and "pull_request" not in i
            ]
            return {"ok": True, "count": len(issues), "issues": issues}
        except GitHubToolError as exc:
            return _err(exc)

    def get_issue(repo: str, number: int) -> dict:
        try:
            repo_id = validate_repo_identifier(repo)
            if number < 1:
                return {"ok": False, "error": "issue number must be positive", "code": "invalid"}
            data = client.get(f"repos/{repo_id}/issues/{number}")
            return {
                "ok": True,
                "number": data.get("number"),
                "title": data.get("title"),
                "state": data.get("state"),
                "created_at": data.get("created_at"),
                "body": (data.get("body") or "")[:10000],
                "url": data.get("html_url"),
            }
        except GitHubToolError as exc:
            return _err(exc)

    def list_pull_requests(repo: str, state: str = "open", per_page: int = 10) -> dict:
        try:
            repo_id = validate_repo_identifier(repo)
            if state not in ("open", "closed", "all"):
                return {"ok": False, "error": "state must be open|closed|all", "code": "invalid"}
            per = max(1, min(per_page, 100))
            data = client.get(f"repos/{repo_id}/pulls", params={"state": state, "per_page": per})
            prs = [
                {
                    "number": p.get("number"),
                    "title": p.get("title"),
                    "state": p.get("state"),
                    "created_at": p.get("created_at"),
                    "user": (p.get("user") or {}).get("login"),
                    "merged": p.get("merged"),
                }
                for p in data
                if isinstance(p, dict)
            ]
            return {"ok": True, "count": len(prs), "pull_requests": prs}
        except GitHubToolError as exc:
            return _err(exc)

    def get_pull_request(repo: str, number: int) -> dict:
        try:
            repo_id = validate_repo_identifier(repo)
            if number < 1:
                return {"ok": False, "error": "pr number must be positive", "code": "invalid"}
            data = client.get(f"repos/{repo_id}/pulls/{number}")
            return {
                "ok": True,
                "number": data.get("number"),
                "title": data.get("title"),
                "state": data.get("state"),
                "created_at": data.get("created_at"),
                "body": (data.get("body") or "")[:10000],
                "additions": data.get("additions"),
                "deletions": data.get("deletions"),
                "changed_files": data.get("changed_files"),
                "url": data.get("html_url"),
            }
        except GitHubToolError as exc:
            return _err(exc)

    def search_repositories(query: str, per_page: int = 10) -> dict:
        try:
            q = validate_query(query)
            per = max(1, min(per_page, 100))
            data = client.get("search/repositories", params={"q": q, "per_page": per})
            items = [
                {
                    "full_name": r.get("full_name"),
                    "description": r.get("description"),
                    "stars": r.get("stargazers_count"),
                    "language": r.get("language"),
                    "updated_at": r.get("updated_at"),
                }
                for r in (data.get("items") or [])
                if isinstance(r, dict)
            ]
            return {"ok": True, "total": data.get("total_count"), "repositories": items}
        except GitHubToolError as exc:
            return _err(exc)

    def search_code(query: str, per_page: int = 10) -> dict:
        try:
            q = validate_query(query)
            per = max(1, min(per_page, 100))
            data = client.get("search/code", params={"q": q, "per_page": per})
            items = [
                {
                    "name": r.get("name"),
                    "path": r.get("path"),
                    "repository": (r.get("repository") or {}).get("full_name"),
                }
                for r in (data.get("items") or [])
                if isinstance(r, dict)
            ]
            return {"ok": True, "total": data.get("total_count"), "results": items}
        except GitHubToolError as exc:
            return _err(exc)

    return [
        _spec(
            "github_repo_info",
            "获取仓库元数据（许可证/星标/活跃度/默认分支）",
            {"repo": "str"},
            repo_info,
        ),
        _spec(
            "github_read_file",
            "读取仓库内单个文件（UTF-8 文本）",
            {"repo": "str", "path": "str"},
            read_file,
        ),
        _spec(
            "github_list_directory",
            "列出仓库目录内容",
            {"repo": "str", "path": "str"},
            list_directory,
        ),
        _spec(
            "github_list_commits", "列出最近提交", {"repo": "str", "per_page": "int"}, list_commits
        ),
        _spec(
            "github_list_issues",
            "列出 Issues（不含 PR）",
            {"repo": "str", "state": "str", "per_page": "int"},
            list_issues,
        ),
        _spec("github_get_issue", "读取单个 Issue", {"repo": "str", "number": "int"}, get_issue),
        _spec(
            "github_list_pull_requests",
            "列出 Pull Requests",
            {"repo": "str", "state": "str", "per_page": "int"},
            list_pull_requests,
        ),
        _spec(
            "github_get_pull_request",
            "读取单个 Pull Request",
            {"repo": "str", "number": "int"},
            get_pull_request,
        ),
        _spec(
            "github_search_repositories",
            "搜索仓库",
            {"query": "str", "per_page": "int"},
            search_repositories,
        ),
        _spec(
            "github_search_code",
            "搜索代码（需 Token）",
            {"query": "str", "per_page": "int"},
            search_code,
        ),
    ]
