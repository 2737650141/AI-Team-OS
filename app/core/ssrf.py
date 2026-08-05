"""统一 SSRF 防护（006 四.4/7.2）：Provider 与 web_fetch 共用。

拒绝：localhost/环回/RFC1918/链路本地/保留/组播/云元数据/域名解析到内网/
解析失败。仅 https（allow_local 时允许 http 本地模式）。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal", "metadata"}


def blocked_host_reason(host: str) -> str | None:
    """返回拒绝原因或 None（放行）。"""
    lowered = host.lower().rstrip(".")
    if lowered in ("localhost", "127.0.0.1", "::1"):
        return f"localhost/loopback host rejected: {host}"
    if lowered in _METADATA_HOSTS or lowered.endswith(".internal"):
        return f"metadata/internal host rejected: {host}"
    try:
        ipaddress.ip_address(lowered)
    except ValueError:
        try:
            infos = socket.getaddrinfo(lowered, None)
        except OSError:
            return f"hostname resolution failed (rejected): {host}"
        for info in infos:
            reason = blocked_ip_reason(str(info[4][0]))
            if reason:
                return f"{reason} (resolved from {host})"
        return None
    return blocked_ip_reason(lowered)


def blocked_ip_reason(ip: str) -> str | None:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    ):
        return f"non-public IP rejected: {ip}"
    return None


def validate_http_url(url: str, allow_http: bool = False) -> str:
    """URL 校验（006 7.2）：scheme/凭据/主机/端口全部检查，返回规范化 URL。"""
    if len(url) > 4096:
        raise ValueError("url too long")
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme == "https":
        pass
    elif scheme == "http":
        if not allow_http:
            raise ValueError("http url rejected (https only)")
    else:
        raise ValueError(f"unsupported scheme rejected: {scheme or '(none)'}")
    if parsed.username or parsed.password:
        raise ValueError("url with embedded credentials rejected")
    if not parsed.hostname:
        raise ValueError("url missing host")
    reason = blocked_host_reason(parsed.hostname)
    if reason:
        raise ValueError(f"url rejected: {reason}")
    if parsed.port is not None and parsed.port not in (80, 443):
        raise ValueError(f"non-standard port rejected: {parsed.port}")
    return url
