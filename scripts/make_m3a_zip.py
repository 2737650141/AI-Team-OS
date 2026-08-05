"""打包 M3-A 源码证据包（artifacts/review/m3a-source.zip）。

包含：源码（app/tests/docs/pyproject/.gitignore/.github）、M3A_EVIDENCE、
pytest 原始输出、Ruff/mypy 输出、demo 演示产物、Git log/status。
排除：.env、.venv、.reasonix、*.db、*.sqlite、API Key 模式。
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "review" / "m3a-source.zip"

INCLUDE_DIRS = ["app", "tests", "docs", "scripts"]
INCLUDE_FILES = ["pyproject.toml", ".gitignore", ".env.example", ".github"]
DEMO_DIR = ROOT / "artifacts" / "demo"

# 敏感模式：任何命中即拒绝打包（源码包不得包含密钥/凭据/数据库）
SENSITIVE = [
    re.compile(r"sk-[A-Za-z0-9]{16,}", re.I),
    re.compile(r"api[_-]?key\s*=\s*['\"]?[A-Za-z0-9]{16,}", re.I),
    re.compile(r"-----BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY-----"),
]
SENSITIVE_EXEMPT = {".env.example", "test_audit.py"}  # 模板占位符 / redact 功能测试样本（假密钥）

BANNED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".p8"}


def scan_text(text: str, path: str) -> list[str]:
    if path in SENSITIVE_EXEMPT:
        return []
    hits = [p.pattern for p in SENSITIVE if p.search(text)]
    return hits


def main() -> None:
    out = OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    scanned = 0
    total_bytes = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for base in INCLUDE_DIRS:
            root = ROOT / base
            if not root.exists():
                continue
            for p in sorted(root.rglob("*")):
                if p.is_dir():
                    continue
                if p.suffix.lower() in BANNED_SUFFIXES:
                    print(f"excluded (suffix): {p}")
                    continue
                if any(part.startswith(".") for part in p.parts) or "__pycache__" in p.parts:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
                scanned += 1
                hits = scan_text(text, p.name)
                if hits:
                    print(f"SENSITIVE BLOCKED: {p} -> {hits}")
                    raise SystemExit(1)
                zf.write(p, p.relative_to(ROOT).as_posix())
                count += 1
                total_bytes += len(text.encode("utf-8"))
        # 证据文件（M3A_EVIDENCE.md 已随 docs/ 目录打包）
        evidence = [
            ROOT / "artifacts" / "review" / "m3a-pytest-verbose.txt",
            ROOT / "artifacts" / "review" / "m3a-ruff-check.txt",
            ROOT / "artifacts" / "review" / "m3a-ruff-format.txt",
            ROOT / "artifacts" / "review" / "m3a-mypy.txt",
            ROOT / "artifacts" / "review" / "m3a-git-log.txt",
            ROOT / "artifacts" / "review" / "m3a-git-status.txt",
            ROOT / "artifacts" / "review" / "m3a-git-remote.txt",
        ]
        for p in evidence:
            if p.exists():
                zf.write(p, p.relative_to(ROOT).as_posix())
                count += 1
        for p in sorted(DEMO_DIR.glob("m3a_*")):
            zf.write(p, p.relative_to(ROOT).as_posix())
            count += 1
    print(f"m3a-source.zip: {count} files, {total_bytes} bytes")
    print(f"sensitive scan: clean ({scanned} source files scanned)")


if __name__ == "__main__":
    main()
