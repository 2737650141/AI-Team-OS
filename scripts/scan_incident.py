"""SEC-01 泄漏定位（008 2.2）：脱敏扫描 reasonix.toml 及其凭据。

只输出元数据与 sha256(secret) 前 12 位指纹，绝不在任何输出中显示凭据原文。
检查范围：
- git log --all 中含 reasonix.toml 的提交（首次进入 / 最后存在 / blob sha）
- reflog / stash / fsck 悬空对象
- 证据 zip 与 artifacts 中的同名条目
- 工作树 / .reasonix / tmp 残留
用法：python scripts/scan_incident.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

# 共享秘密模式（与运行时脱敏同源，避免漂移）；subject 输出经 redact 脱敏
from app.core.secrets import SECRET_PATTERNS, redact

ROOT = Path(__file__).resolve().parent.parent


def sh(*args: str) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (r.stdout or "").strip()


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def main() -> int:
    findings: list[str] = []

    # 1. 含 reasonix.toml 的提交（git log --all）
    print("== git log --all -- reasonix.toml ==")
    out = redact(sh("log", "--all", "--format=%H %s", "--", "reasonix.toml"))
    print(out or "(none)")
    blob = ""
    commits = [line.split()[0] for line in out.splitlines() if line.strip()]
    if commits:
        first, last = commits[-1], commits[0]
        print(f"first_commit={first} last_commit={last} count={len(commits)}")
        # 凭据内容位于首次带入提交（移除提交中文件已删，rev-parse 无结果）
        blob = sh("rev-parse", f"{first}:reasonix.toml")
        print(f"blob_sha={blob}")
        raw = subprocess.run(
            ["git", "cat-file", "blob", blob],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
        # 用共享模式提取首个凭据；只输出指纹（绝不输出原文）
        m = next((p.search(raw) for p in SECRET_PATTERNS if p.search(raw)), None)
        if m:
            print(f"credential_fingerprint=sha256:{fingerprint(m.group(0))}")
            print("credential_type=API key (sk-) / provider=openai-compatible (unset base_url)")
        else:
            print("credential_fingerprint=(no credential pattern found in blob)")

    # 2. reflog 引用泄漏提交
    print("\n== git reflog --all (reasonix.toml 相关提交引用) ==")
    reflog = sh("reflog", "--all", "--format=%H %gs")
    leaked_heads = set(commits)
    hit = [redact(ln) for ln in reflog.splitlines() if ln.split()[0] in leaked_heads]
    print(hit if hit else "(no reflog reference to leaked commits)")

    # 3. stash
    print("\n== git stash list ==")
    st = sh("stash", "list")
    print(st or "(no stash)")
    if st:
        for line in st.splitlines():
            sid = line.split(":")[0]
            present = bool(sh("ls-tree", "-r", sid, "--", "reasonix.toml"))
            print(f"stash={sid} reasonix.toml_present={present}")

    # 4. fsck 悬空对象（泄漏 blob 是否仍可达/悬空）
    print("\n== git fsck --full --no-reflogs ==")
    fsck = sh("fsck", "--full", "--no-reflogs")
    print(fsck or "(clean)")
    if blob:
        dangling_hit = any(blob in ln for ln in fsck.splitlines())
        print(f"leaked_blob_dangling={dangling_hit}")

    # 5. 证据 zip / artifacts 中的 reasonix.toml 条目
    print("\n== artifacts zips ==")
    for z in sorted((ROOT / "artifacts").rglob("*.zip")):
        try:
            with zipfile.ZipFile(z) as zf:
                names = [n for n in zf.namelist() if "reasonix.toml" in n.lower()]
            print(f"{z.relative_to(ROOT)}: reasonix_entries={names or '(none)'}")
        except Exception as exc:  # noqa: BLE001
            print(f"{z.relative_to(ROOT)}: ERROR {exc}")

    # 6. 工作树 / .reasonix / tmp 残留
    print("\n== filesystem leftovers ==")
    leftovers = []
    for root_dir in (ROOT, ROOT / ".reasonix"):
        if not root_dir.exists():
            continue
        for p in root_dir.rglob("reasonix.toml"):
            leftovers.append(str(p.relative_to(ROOT)))
    for p in sorted(leftovers):
        findings.append(f"leftover: {p}")
    print(leftovers or "(no reasonix.toml in worktree/.reasonix)")

    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
