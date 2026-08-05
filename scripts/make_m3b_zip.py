"""打包 M3-B 源码证据包（artifacts/review/m3b-source.zip）。

包含：源码（app/tests/docs/scripts/pyproject/.gitignore/.env.example/.github）、
M3B_EVIDENCE、pytest 原始输出、Ruff/mypy 输出、demo 演示产物、Git log/status。
排除：.env、.venv、.reasonix、*.db、*.sqlite、runtime/、API Key 模式。
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
    ".env.example": "模板占位符（SK-PLACEHOLDER），非真实凭据",
    "tests/test_audit.py": "redact 功能测试样本（假密钥用于断言脱敏），非真实凭据",
    "tests/test_m3_governance.py": "API Key 不泄漏测试样本（假值），非真实凭据",
    "tests/test_m3_low_fixes.py": "统一脱敏测试样本（假值），非真实凭据",
    "tests/test_m3b_local_evidence_mcp.py": "敏感文件拒绝测试 fixture（假内容），非真实凭据",
    "tests/test_m3b_github_web.py": "GitHub Token 不泄漏测试样本（假值），非真实凭据",
}

BANNED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".p12", ".p8"} | SENSITIVE_SUFFIXES
BANNED_DIRS = {"__pycache__", ".pytest_cache", "runtime", ".git", ".venv", ".reasonix"}


def scan_text(text: str, path: str) -> list[str]:
    """秘密检测：统一逻辑 + 相对路径豁免（打印原因）。"""
    if path in SENSITIVE_EXEMPT:
        print(f"exempt (reason: {SENSITIVE_EXEMPT[path]}): {path}")
        return []
    return scan_secrets(text)


def _add_file(zf: zipfile.ZipFile, p: Path, arcname: str) -> int:
    text = p.read_text(encoding="utf-8", errors="replace")
    # 豁免按相对路径精确匹配（006 四.5）
    hits = scan_text(text, arcname)
    if hits:
        print(f"SENSITIVE BLOCKED: {p} -> {hits}")
        raise SystemExit(1)
    zf.write(p, arcname)
    return len(text.encode("utf-8"))


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
                    if sub.is_dir() or any(part in BANNED_DIRS for part in sub.parts):
                        continue
                    scanned += 1
                    total_bytes += _add_file(zf, sub, sub.relative_to(ROOT).as_posix())
                    count += 1
            else:
                scanned += 1
                total_bytes += _add_file(zf, p, p.relative_to(ROOT).as_posix())
                count += 1
        # 目录（app/tests/docs/scripts）
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
                if any(part.startswith(".") for part in p.parts) or any(
                    part in BANNED_DIRS for part in p.parts
                ):
                    continue
                scanned += 1
                total_bytes += _add_file(zf, p, p.relative_to(ROOT).as_posix())
                count += 1
        # 证据文件（M3B_EVIDENCE.md 已随 docs/ 目录打包）
        evidence = [
            ROOT / "artifacts" / "review" / "m3b-pytest-verbose.txt",
            ROOT / "artifacts" / "review" / "m3b-ruff-check.txt",
            ROOT / "artifacts" / "review" / "m3b-ruff-format.txt",
            ROOT / "artifacts" / "review" / "m3b-mypy.txt",
            ROOT / "artifacts" / "review" / "m3b-git-log.txt",
            ROOT / "artifacts" / "review" / "m3b-git-status.txt",
            ROOT / "artifacts" / "review" / "m3b-git-remote.txt",
        ]
        for p in evidence:
            if p.exists():
                zf.write(p, p.relative_to(ROOT).as_posix())
                count += 1
        for p in sorted(DEMO_DIR.glob("m3b_*")):
            zf.write(p, p.relative_to(ROOT).as_posix())
            count += 1
    print(f"m3b-source.zip: {count} files, {total_bytes} bytes")
    print(f"sensitive scan: clean ({scanned} source files scanned)")


if __name__ == "__main__":
    main()
