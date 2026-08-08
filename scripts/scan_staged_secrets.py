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
EXEMPT_PREFIXES = ("SK-PLACEHOLDER", "TEST-TOKEN-")  # 前缀锚定（值起点）


def _is_exempt_token(matched: str) -> bool:
    """豁免仅当匹配**值**以测试前缀开头（前缀锚定，非子串搜索）。

    防止 `sk-<real>SK-PLACEHOLDER`（嵌入标记）绕过（sa_20260808_100103 LOW-1）。
    Bearer 形式（Authorization: Bearer <token>）先剥离 "Bearer " 再判断。
    """
    val = matched.strip("'\" \t")
    if val.upper().startswith("BEARER "):
        val = val[7:].strip()
    val = re.split(r"[=:]", val, maxsplit=1)[-1].strip("'\" \t")
    up = val.upper()
    return any(up.startswith(p.upper()) for p in EXEMPT_PREFIXES)


def _fingerprint(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def scan_text(text: str) -> list[str]:
    """逐行扫描 + 整段 DOTALL 扫描（多行 PEM 私钥）。

    命中秘密模式且匹配值不含测试前缀豁免 → 报告（只报模式 + 内容 sha256 指纹，
    绝不回显凭据原文，sa_20260808_100103 LOW-2）。空列表 = 干净。
    """
    hits: list[str] = []
    for line in text.splitlines():
        for pat in SECRET_PATTERNS:
            if pat.flags & re.DOTALL:
                continue  # 多行模式在整段扫描处理
            m = pat.search(line)
            if m and not _is_exempt_token(m.group(0)):
                hits.append(f"{pat.pattern[:50]} matched (sha256:{_fingerprint(line)})")
                break
    # 多行模式（PEM 私钥整块）对整段文本匹配；豁免按匹配内容判断
    for pat in SECRET_PATTERNS:
        if not (pat.flags & re.DOTALL):
            continue
        m = pat.search(text)
        if m and not _is_exempt_token(m.group(0)):
            hits.append(f"{pat.pattern[:50]} matched multiline (sha256:{_fingerprint(text)})")
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
