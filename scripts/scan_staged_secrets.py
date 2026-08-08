"""SEC-01 防复发（008 2.7-2）：提交前秘密扫描。

扫描暂存区（git diff --cached）内容：命中统一 SECRET_PATTERNS 的行若不含
明确测试前缀豁免（SK-PLACEHOLDER 等，008 2.7-6）即阻塞提交，阻止真实凭据入库。
由 githooks/pre-commit 调用；也可手动运行。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from app.core.secrets import SECRET_PATTERNS

ROOT = Path(__file__).resolve().parent.parent

# 明确测试前缀豁免（008 2.7-6）：测试假密钥必须使用这些前缀，扫描放行
EXEMPT_PREFIXES = (re.compile(r"SK-PLACEHOLDER", re.I), re.compile(r"TEST-TOKEN-"))


def _is_exempt(line: str) -> bool:
    return any(p.search(line) for p in EXEMPT_PREFIXES)


def scan_text(text: str) -> list[str]:
    """逐行扫描，返回命中秘密模式且非测试前缀豁免的报告列表（空 = 干净）。"""
    hits: list[str] = []
    for line in text.splitlines():
        if _is_exempt(line):
            continue
        for pat in SECRET_PATTERNS:
            m = pat.search(line)
            if m:
                hits.append(f"{pat.pattern[:50]} matched in: {line[:40]}...")
                break
    return hits


def main() -> int:
    r = subprocess.run(
        ["git", "diff", "--cached", "--no-color"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    hits = scan_text(r.stdout or "")
    if hits:
        print("SEC-01 pre-commit scan BLOCKED: staged changes match secret patterns:")
        for h in hits:
            print("  " + h)
        print("移除真实凭据（测试用 SK-PLACEHOLDER 前缀）后重新提交。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
