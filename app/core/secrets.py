"""统一脱敏与秘密检测（006 四.3/4）：运行时脱敏与打包扫描共用同一模式集。

- redact()：审计/快照/错误消息使用的脱敏函数（替换为 ***）。
- scan_text()：打包与静态扫描使用的秘密检测（返回命中模式）。
- 覆盖：API Key（sk-*）、通用 api_key/token/password/secret 赋值、
  PEM/PKCS#8/RSA/OPENSSH/EC/PGP 私钥块、Authorization Header。
"""

from __future__ import annotations

import re

# ---- 统一秘密模式（运行时脱敏 + 打包扫描共用） ----
SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}", re.I),
    re.compile(r"ghp_[A-Za-z0-9]{20,}", re.I),  # GitHub PAT
    re.compile(r"gho_[A-Za-z0-9]{20,}", re.I),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key
    re.compile(
        r"(?i)(api[_-]?key|token|secret|password|passwd|authorization)\s*[=:]\s*['\"]?[A-Za-z0-9._/-]{12,}"
    ),
    # PEM 私钥整块（含内容，DOTALL）：BEGIN 与 END 之间全部替换
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.DOTALL | re.I,
    ),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I),
]


# ---- 运行时脱敏 ----
def redact(text: str) -> str:
    """脱敏：命中秘密模式的部分替换为 ***（006 四.4：统一逻辑）。"""
    result = text
    for pattern in SECRET_PATTERNS:
        result = pattern.sub("***", result)
    return result


# ---- 打包/静态扫描 ----
def scan_text(text: str) -> list[str]:
    """返回命中秘密模式的正则原文列表（空列表 = 干净）。"""
    return [p.pattern for p in SECRET_PATTERNS if p.search(text)]


# 敏感文件后缀/名称（本地文件只读工具与打包共用，006 8.3）
SENSITIVE_FILENAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "credentials",
    "credentials.json",
    "secrets",
    "secrets.json",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".p8", ".pfx", ".ppk"}
SENSITIVE_DIRS = {".ssh", ".aws", ".gnupg", ".kube", ".git"}
