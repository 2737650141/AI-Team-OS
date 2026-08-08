"""SEC-01 防复发（008 2.7-5）：安装安全 pre-commit Hook。

仅复制仓库内受审查的 githooks/pre-commit 到 .git/hooks/，不执行其他操作。
用法：python scripts/install_hooks.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    src = ROOT / "githooks" / "pre-commit"
    dst_dir = ROOT / ".git" / "hooks"
    dst = dst_dir / "pre-commit"
    if not src.exists():
        print(f"missing template: {src}")
        return 1
    dst_dir.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        import time

        backup = dst.with_name(f"pre-commit.bak-{int(time.time())}")
        shutil.copy2(dst, backup)
        print(f"backed up existing hook: {backup}")
    shutil.copy2(src, dst)
    # POSIX：确保 exec 位（git 忽略无执行位的 hook，静默失效）
    try:
        dst.chmod(dst.stat().st_mode | 0o111)
    except OSError:
        pass
    print(f"installed pre-commit hook: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
