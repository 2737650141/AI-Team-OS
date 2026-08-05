"""打包 M3-B 源码证据包（artifacts/review/m3b-source.zip）。

包含：源码（app/tests/docs/scripts/pyproject/.gitignore/.env.example/.github）、M3B_EVIDENCE、
pytest 原始输出、Ruff/mypy 输出、demo 演示产物、Git log/status。
排除：.env、.venv、.reasonix、*.db、*.sqlite、API Key 模式。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.core.secrets import SENSITIVE_SUFFIXES
from app.core.secrets import scan_text as scan_secrets

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "review" / "m3b-source.zip"

INCLUDE_DIRS = ["app", "tests", "docs", "scripts"]
INCLUDE_FILES = ["pyproject.toml", ".gitignore", ".env.example", ".github"]
DEMO_DIR = ROOT / "artifacts" / "demo"

# 统一秘密检测（006 四.3/4）：模式集与运行时脱敏共用（app.core.secrets）
# 豁免按相对路径精确匹配（006 四.5），并打印豁免原因
SENSITIVE_EXEMPT = {
    ".env.example": "模板占位符（sk-placeholder-replace-me），非真实凭据",
    "tests/test_audit.py": "redact 功能测试样本（假密钥用于断言脱敏），非真实凭据",
}

BANNED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".p12", ".p8"} | SENSITIVE_SUFFIXES


def scan_text(text: str, path: str) -> list[str]:
    """秘密检测：统一逻辑 + 相对路径豁免（打印原因）。"""
    if path in SENSITIVE_EXEMPT:
        print(f"exempt (reason: {SENSITIVE_EXEMPT[path]}): {path}")
        return []
    return scan_secrets(text)


def main() -> None:
    out = OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    scanned = 0
    total_bytes = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        # 独立文件（pyproject/.gitignore/.env.example/.github）
        for name in INCLUDE_FILES:
            p = ROOT / name
            if not p.exists():
                continue
            if p.is_dir():
                for sub in sorted(p.rglob("*")):
                    if sub.is_dir() or "__pycache__" in sub.parts:
                        continue
                    text = sub.read_text(encoding="utf-8", errors="replace")
                    scanned += 1
                    hits = scan_text(text, sub.name)
                    if hits:
                        print(f"SENSITIVE BLOCKED: {sub} -> {hits}")
                        raise SystemExit(1)
                    zf.write(sub, sub.relative_to(ROOT).as_posix())
                    count += 1
            else:
                text = p.read_text(encoding="utf-8", errors="replace")
                scanned += 1
                hits = scan_text(text, p.name)
                if hits:
                    print(f"SENSITIVE BLOCKED: {p} -> {hits}")
                    raise SystemExit(1)
                zf.write(p, p.relative_to(ROOT).as_posix())
                count += 1
                total_bytes += len(text.encode("utf-8"))
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
