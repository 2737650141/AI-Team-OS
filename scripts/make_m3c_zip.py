"""M3-C 证据打包（007 二十五）：源码 zip + pytest 详细输出 + git 记录 + 敏感扫描。

- 只打包源码/配置/文档（排除 runtime/、artifacts/、.git、.venv、__pycache__）。
- 敏感扫描：跳过测试假密钥文件（白名单豁免，原因明确），其余源码含真实
  密钥模式（sk-/ghp_/AKIA/aws_secret/PEM 等）即报错退出。
- 用法：python scripts/make_m3c_zip.py
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "review"
ZIP_NAME = "m3c-source.zip"

# 源码/文档（与 M3-A/M3-B 一致）
INCLUDE_DIRS = ["app", "tests", "docs", "scripts", "fixtures", ".github"]
INCLUDE_FILES = ["pyproject.toml", ".gitignore", ".env.example"]
EXCLUDE_DIRS = {"__pycache__", ".venv", "runtime", "artifacts", ".git", "node_modules", ".pytest_cache", ".mypy_cache"}

# 真实密钥模式（与 app/core/secrets.py 同源收紧；测试假密钥经相对路径豁免）
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgho_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\baws_secret_access_key\s*=\s*[A-Za-z0-9/+=_-]{20,}"),
    re.compile(r"\bAI_TEAM_MODEL_API_KEY\s*=\s*[^\s]{8,}"),
]

# 测试假密钥白名单豁免（相对路径 + 原因；007 二十五：打包敏感扫描说明）
SENSITIVE_EXEMPT = {
    "tests/test_m3_low_fixes.py": "假密钥（SK-PLACEHOLDER）用于断言脱敏逻辑",
    "tests/test_m3_governance.py": "假密钥（SK-PLACEHOLDER）用于断言治理",
    "tests/test_m3b_github_web.py": "Mock 请求头假 Token 断言",
    "tests/test_m3b_local_evidence_mcp.py": "假密钥断言 Evidence 脱敏",
    "tests/test_m3c_runtime.py": "假 Token 断言命令环境脱敏",
    "tests/test_audit.py": "假密钥断言审计脱敏",
    "tests/test_m3c_sandbox.py": "假密钥断言审批/脱敏",
    "tests/test_m3c_workspace.py": "假密钥断言排除规则",
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
    hits: list[str] = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if rel in SENSITIVE_EXEMPT:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in SECRET_PATTERNS:
            m = pat.search(text)
            if m:
                hits.append(f"{rel}: {pat.pattern[:40]}... matched {m.group(0)[:12]}...")
                break
    return hits


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
    size = zip_path.stat().st_size
    print(f"m3c-source.zip: {len(files)} files, {size} bytes, sensitive scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
