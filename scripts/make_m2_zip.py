"""生成 artifacts/review/m2-source.zip（004 二十一）。

包含：app、tests、docs、pyproject.toml、配置文件、测试原始输出、CLI 演示输出、Git 状态与日志。
排除：.venv、.reasonix、SQLite 数据库、临时日志、API Key、上游仓库。
打包后立即做敏感扫描（.env / 密钥 / 数据库文件）。
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "review" / "m2-source.zip"

INCLUDE = [
    "app",
    "tests",
    "docs",
    "pyproject.toml",
    ".gitignore",
    ".env.example",
    ".github",
    "artifacts/demo",
    "artifacts/review/m2-pytest-verbose.txt",
    "artifacts/review/m2-git-log.txt",
    "artifacts/review/m2-git-status.txt",
]

EXCLUDE_SUFFIXES = (".db", ".sqlite", ".pyc", ".log")
EXCLUDE_NAMES = {".venv", ".reasonix", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDE:
            src = ROOT / rel
            if src.is_dir():
                for path in sorted(src.rglob("*")):
                    if not path.is_file():
                        continue
                    if any(part in EXCLUDE_NAMES for part in path.parts):
                        continue
                    if path.suffix.lower() in EXCLUDE_SUFFIXES:
                        continue
                    zf.write(path, path.relative_to(ROOT).as_posix())
                    count += 1
            elif src.is_file():
                zf.write(src, src.relative_to(ROOT).as_posix())
                count += 1
    print(f"m2-source.zip: {count} files, {OUT.stat().st_size} bytes")

    # 敏感扫描：压缩包内不得出现真实密钥/数据库文件（.env.example 是模板，允许）
    banned = (".pem", ".key", "id_rsa", "token")
    exact_banned = (".env", ".db", ".sqlite")
    with zipfile.ZipFile(OUT) as zf:
        offenders = [
            n
            for n in zf.namelist()
            if any(b in n.lower() for b in banned)
            or any(n.lower().endswith(b) for b in exact_banned)
        ]
    if offenders:
        raise SystemExit(f"sensitive scan failed: {offenders}")
    print("sensitive scan: clean")


if __name__ == "__main__":
    main()
