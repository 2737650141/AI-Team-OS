"""UI-01 证据打包（010 六十）：ui01-source.zip + 敏感扫描。

包含：后端源码、前端源码（web/ 不含 node_modules/dist）、测试、文档、
截图、演示产物（artifacts/demo/）、SSE/approval/diff/settings 示例。
排除：.env、.reasonix、runtime/、artifacts/review 内部 zip、node_modules、dist。
扫描复用 app.core.secrets.SECRET_PATTERNS + 测试假密钥文件豁免（同 m3c）。
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from app.core.secrets import SECRET_PATTERNS

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "review"
ZIP_NAME = "ui01-source.zip"

INCLUDE_DIRS = ["app", "tests", "docs", "scripts", "web", "fixtures", ".github", "githooks"]
INCLUDE_FILES = ["pyproject.toml", ".gitignore", ".env.example"]
EXCLUDE_DIRS = {
    "__pycache__",
    ".venv",
    "runtime",
    "artifacts",
    ".git",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "test-results",
    "playwright-report",
}

SENSITIVE_EXEMPT = {
    "tests/test_m3_low_fixes.py": "假密钥（SK-PLACEHOLDER）用于断言脱敏逻辑",
    "tests/test_m3_governance.py": "假密钥（SK-PLACEHOLDER）用于断言治理",
    "tests/test_m3b_github_web.py": "Mock 请求头假 Token 断言",
    "tests/test_m3b_local_evidence_mcp.py": "假密钥断言 Evidence 脱敏",
    "tests/test_m3c_runtime.py": "假 Token 断言命令环境脱敏",
    "tests/test_sec01_incident.py": "SEC-01 回归测试（SK-PLACEHOLDER 前缀假密钥）",
    "tests/test_audit.py": "假密钥断言审计脱敏",
    "tests/test_m3c_sandbox.py": "假密钥断言审批/脱敏",
    "tests/test_m3c_workspace.py": "假密钥断言排除规则",
    "tests/test_secret_connections.py": "Secret 测试（SK-PLACEHOLDER/拼接假密钥）",
    "web/src/pages/Settings.test.tsx": "Secret 表单测试（SK-PLACEHOLDER 前缀）",
    ".env.example": "占位符（示例配置，非真实密钥）",
}


def iter_files() -> list[Path]:
    files: list[Path] = []
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and not any(part in EXCLUDE_DIRS for part in p.parts):
                files.append(p)
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.exists():
            files.append(p)
    return files


def scan(files: list[Path]) -> list[str]:
    import re as _re

    # Pydantic 字段声明（`api_key: str | None = Field(...)`）不是真实密钥赋值
    field_decl = _re.compile(
        r"^\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*(str|int|float|bool|dict|list|Field|BaseModel|Any)"
    )
    hits: list[str] = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if rel in SENSITIVE_EXEMPT:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            # Pydantic 字段声明（`api_key: str | None = Field(...)`）非密钥赋值；
            # 但**带字符串默认值**（`= "sk-..."`）的行不豁免（MEDIUM 盲点修复，
            # sa_20260808_120306）——默认值含密钥属反模式，交由扫描拦截
            if field_decl.match(line) and "=" not in line:
                continue
            if field_decl.match(line) and not re_search_string_default(line):
                continue
            for pat in SECRET_PATTERNS:
                if pat.search(line):
                    hits.append(f"{rel}: {pat.pattern[:40]}...")
                    break
    return hits


def re_search_string_default(line: str) -> bool:
    """行内是否含字符串默认值（`= "…"` / `= '…'`）。"""
    import re as _re

    return bool(_re.search(r'=\s*["\']', line))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    files = iter_files()
    hits = scan(files)
    if hits:
        print("SENSITIVE SCAN FAILED:")
        for h in hits:
            print("  " + h)
        return 1
    zip_path = OUT / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(ROOT).as_posix())
    print(f"{ZIP_NAME}: {len(files)} files, {zip_path.stat().st_size} bytes, sensitive scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
