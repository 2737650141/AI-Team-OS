"""SEC-01 staged secret scan with an explicit test-fixture policy.

The scanner inspects the staged blob for every changed path.  A synthetic
secret is exempt only when its value is immediately prefixed with
``AI_TEAM_OS_TEST_`` and the staged path is under ``tests/``.  Comments,
variable names, non-test paths, and unmarked secret-shaped values remain
blocking.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from app.core.secrets import SECRET_PATTERNS

ROOT = Path(__file__).resolve().parent.parent

TEST_FIXTURE_MARKER = "AI_TEAM_OS_TEST_"
TESTS_PATH_PREFIX = "tests/"
LEGACY_NON_TEST_PLACEHOLDERS = {
    ("app/runner.py", "TEST-TOKEN-LOCAL-OLLAMA"),
}


def _is_test_path(source_path: str | None) -> bool:
    if not source_path:
        return False
    normalized = source_path.replace("\\", "/").lstrip("./")
    return normalized.startswith(TESTS_PATH_PREFIX)


def _matched_value(matched: str) -> str:
    value = matched.strip("'\" \t")
    if re.match(r"(?i)^Bearer\s+", value):
        value = re.sub(r"(?i)^Bearer\s+", "", value, count=1)
    return re.split(r"[=:]", value, maxsplit=1)[-1].strip("'\" \t")


def _is_test_fixture_match(text: str, match: re.Match[str], source_path: str | None) -> bool:
    """Allow only a marker immediately attached to the matched secret value.

    This deliberately does not accept a marker in a comment or variable name.
    For patterns such as ``sk-...`` where the regex starts after the marker,
    the marker must be the exact preceding substring.
    """
    if not _is_test_path(source_path):
        return False

    value = _matched_value(match.group(0))
    if value.startswith(TEST_FIXTURE_MARKER):
        return True

    start = match.start()
    marker_start = start - len(TEST_FIXTURE_MARKER)
    return marker_start >= 0 and text[marker_start:start] == TEST_FIXTURE_MARKER


def _is_legacy_non_test_placeholder(match: re.Match[str], source_path: str | None) -> bool:
    """Keep one pre-existing local-provider sentinel without widening test policy."""
    if not source_path or _is_test_path(source_path):
        return False
    normalized = source_path.replace("\\", "/").lstrip("./")
    return (
        (normalized, "TEST-TOKEN-LOCAL-OLLAMA") in LEGACY_NON_TEST_PLACEHOLDERS
        and _matched_value(match.group(0)) == "TEST-TOKEN-LOCAL-OLLAMA"
    )


def _fingerprint(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def scan_text(text: str, source_path: str | None = None) -> list[str]:
    """Scan text without exposing secret contents.

    ``source_path`` is required for test-fixture exemptions.  Omitting it
    keeps the safe default: every secret-shaped value blocks.
    """
    hits: list[str] = []
    for line in text.splitlines():
        for pat in SECRET_PATTERNS:
            if pat.flags & re.DOTALL:
                continue  # 多行模式在整段扫描处理
            for m in pat.finditer(line):
                if not (
                    _is_test_fixture_match(line, m, source_path)
                    or _is_legacy_non_test_placeholder(m, source_path)
                ):
                    hits.append(f"{pat.pattern[:50]} matched (sha256:{_fingerprint(line)})")
                    break
            else:
                continue
            break
    # 多行模式（PEM 私钥整块）对整段文本匹配；豁免按匹配内容判断
    for pat in SECRET_PATTERNS:
        if not (pat.flags & re.DOTALL):
            continue
        m = pat.search(text)
        if m and not (
            _is_test_fixture_match(text, m, source_path)
            or _is_legacy_non_test_placeholder(m, source_path)
        ):
            hits.append(f"{pat.pattern[:50]} matched multiline (sha256:{_fingerprint(text)})")
    return hits


def main() -> int:
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        print("SEC-01 pre-commit scan BLOCKED: unable to enumerate staged files.")
        return 1

    hits: list[tuple[str, str]] = []
    for path in (p for p in (r.stdout or "").splitlines() if p):
        staged = subprocess.run(
            ["git", "show", f":{path}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if staged.returncode != 0:
            print(f"SEC-01 pre-commit scan BLOCKED: unable to read staged file {path}.")
            return 1
        hits.extend((path, h) for h in scan_text(staged.stdout or "", source_path=path))

    if hits:
        print("SEC-01 pre-commit scan BLOCKED: staged changes match secret patterns:")
        for path, h in hits:
            print(f"  {path}: {h}")
        print("Use AI_TEAM_OS_TEST_ only for synthetic fixtures under tests/; remove real secrets.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
