"""OpenAICompatibleProvider（005 7.x）：Chat Completions 兼容端点。

安全要求：
- 仅 https://，默认拒绝 localhost/环回/RFC1918/链路本地/云元数据（7.3，SSRF 防护）。
- 重定向后再次校验目标地址（httpx follow_redirects=False + 手动校验）。
- 明确连接/读取超时、最大响应体限制、TLS 默认开启、连接复用、User-Agent。
- 不在日志中记录 Authorization（7.2）；API Key 只存于本类私有字段。
- 真实调用必须 AI_TEAM_MODEL_ENABLE_REAL=true（7.4），否则返回确定性配置错误。
"""

from __future__ import annotations

import ipaddress
import json
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.gateway.contracts import (
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
    UsageEstimate,
)

USER_AGENT = "ai-team-os/0.3.0"

# 云元数据地址（169.254.169.254 等）与链路本地
_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal", "metadata"}
_MAX_RESPONSE_BYTES = 1024 * 1024  # 最大响应体 1MB（7.2）


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _blocked_host_reason(host: str) -> str | None:
    """Base URL 安全校验（7.3）：返回拒绝原因或 None（放行）。

    允许 https 域名（含子域）；拒绝 IP 字面量中的环回/RFC1918/链路本地/云元数据，
    拒绝 localhost/内网主机名。
    """
    lowered = host.lower().rstrip(".")
    if lowered in ("localhost", "127.0.0.1", "::1"):
        return f"localhost/loopback host rejected: {host}"
    if lowered in _METADATA_HOSTS or lowered.endswith(".internal"):
        return f"metadata/internal host rejected: {host}"
    # 解析主机名：IP 字面量直接判定
    try:
        ipaddress.ip_address(lowered)
    except ValueError:
        # 域名：解析到内网地址即拒绝（DNS 解析属 SSRF 防护一部分）；
        # 解析失败必须拒绝而非放行（防 DNS rebinding TOCTOU 的解析侧）
        try:
            infos = socket.getaddrinfo(lowered, None)
        except OSError:
            return f"hostname resolution failed (rejected): {host}"
        for info in infos:
            reason = _blocked_ip_reason(str(info[4][0]))
            if reason:
                return f"{reason} (resolved from {host})"
        return None
    return _blocked_ip_reason(lowered)


def _blocked_ip_reason(ip: str) -> str | None:
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


class OpenAICompatibleProvider:
    """OpenAI Chat Completions 兼容 Provider（第一版协议，005 7.1）。"""

    provider_name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_model: str = "",
        enable_real: bool = False,
        timeout_seconds: int = 60,
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
        transport: httpx.BaseTransport | None = None,
        allow_local: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key  # 私有字段：不进入状态/日志/消息
        self._default_model = default_model
        self._enable_real = enable_real
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._allow_local = allow_local
        # 显式超时 + 连接复用 + 不自动重定向（重定向后手动校验，7.2/7.3）
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=timeout_seconds),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
            transport=transport,  # 测试注入 mock transport；生产为 None
        )

    # ---- 契约（005 6） ----
    def generate(self, request: ModelRequest) -> ModelResponse:
        self._assert_ready(request.model)
        url = f"{self._base_url}/chat/completions"
        self._assert_url_allowed(url)
        body = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature
            if request.temperature is not None
            else self._temperature,
            "max_tokens": request.max_output_tokens or self._max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        # 流式读取响应并限制最大字节（006 四.2）：超过 _MAX_RESPONSE_BYTES 立即断开，
        # 不等待完整缓冲
        chunks: list[bytes] = []
        total = 0
        try:
            with self._client.stream("POST", url, json=body, headers=headers) as resp:
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        resp.close()
                        raise ProviderError(
                            ProviderErrorCode.MALFORMED_RESPONSE,
                            "provider response body exceeds limit",
                            provider=self.provider_name,
                            model=request.model,
                        )
                    chunks.append(chunk)
                resp.read()
                status_code = resp.status_code
                resp_headers = resp.headers
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderErrorCode.TIMEOUT,
                "provider request timed out",
                provider=self.provider_name,
                model=request.model,
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderError(
                ProviderErrorCode.CONNECTION_ERROR,
                "provider connection failed",
                provider=self.provider_name,
                model=request.model,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorCode.CONNECTION_ERROR,
                "provider transport error",
                provider=self.provider_name,
                model=request.model,
            ) from exc
        # 重定向：httpx follow_redirects=False，3xx 视为配置错误（7.3：不允许重定向到内网）
        if status_code in (301, 302, 303, 307, 308):
            location = resp_headers.get("location", "")
            reason = (
                _blocked_host_reason(urlparse(location).hostname or "")
                if location
                else "empty redirect"
            )
            raise ProviderError(
                ProviderErrorCode.CONFIG_ERROR,
                f"provider redirect rejected: {reason}",
                provider=self.provider_name,
                model=request.model,
            )
        if status_code == 401:
            raise ProviderError(
                ProviderErrorCode.AUTHENTICATION_ERROR,
                "provider authentication failed",
                provider=self.provider_name,
                model=request.model,
            )
        if status_code == 403:
            raise ProviderError(
                ProviderErrorCode.PERMISSION_ERROR,
                "provider permission denied",
                provider=self.provider_name,
                model=request.model,
            )
        if status_code == 404:
            raise ProviderError(
                ProviderErrorCode.MODEL_NOT_FOUND,
                f"model not found: {request.model}",
                provider=self.provider_name,
                model=request.model,
            )
        if status_code == 429:
            raise ProviderError(
                ProviderErrorCode.RATE_LIMITED,
                "provider rate limited",
                provider=self.provider_name,
                model=request.model,
            )
        if status_code >= 500:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INTERNAL_ERROR,
                "provider internal error",
                provider=self.provider_name,
                model=request.model,
            )
        if status_code != 200:
            raise ProviderError(
                ProviderErrorCode.INVALID_REQUEST,
                f"provider returned status {status_code}",
                provider=self.provider_name,
                model=request.model,
            )
        # 重建响应对象（流式已限长；此处仅防 mock transport 直通超大响应）
        content = b"".join(chunks)
        if len(content) > _MAX_RESPONSE_BYTES:
            raise ProviderError(
                ProviderErrorCode.MALFORMED_RESPONSE,
                "provider response body exceeds limit",
                provider=self.provider_name,
                model=request.model,
            )
        resp = httpx.Response(
            status_code, headers=resp_headers, content=content, request=resp.request
        )
        return self._parse_success(request, resp)

    def estimate_usage(self, request: ModelRequest) -> UsageEstimate:
        """调用前估算（10.1）：输入按 messages 字符粗估；输出按 max_output_tokens 预留。"""
        chars = sum(len(m.get("content", "")) for m in request.messages)
        input_tokens = max(1, chars // 4)
        return UsageEstimate(
            estimated_input_tokens=input_tokens,
            estimated_max_output_tokens=request.max_output_tokens or self._max_output_tokens,
            estimated_max_cost=None,  # 价格由 ModelGateway 按价格表计算；此处不伪造
        )

    def health_check(self) -> ProviderHealth:
        if not self._enable_real:
            return ProviderHealth(
                status="disabled",
                provider=self.provider_name,
                model=self._default_model,
                message="real model calls disabled (AI_TEAM_MODEL_ENABLE_REAL=false)",
                checked_at=_now(),
            )
        if not self._api_key:
            return ProviderHealth(
                status="misconfigured",
                provider=self.provider_name,
                model=self._default_model,
                message="missing API key",
                checked_at=_now(),
            )
        if not self._base_url:
            return ProviderHealth(
                status="misconfigured",
                provider=self.provider_name,
                model=self._default_model,
                message="missing base url",
                checked_at=_now(),
            )
        try:
            self._assert_url_allowed(f"{self._base_url}/chat/completions")
        except ProviderError as exc:
            return ProviderHealth(
                status="misconfigured",
                provider=self.provider_name,
                model=self._default_model,
                message=exc.safe_message,
                checked_at=_now(),
            )
        return ProviderHealth(
            status="healthy",
            provider=self.provider_name,
            model=self._default_model,
            message="configured; real calls enabled",
            checked_at=_now(),
        )

    # ---- 内部 ----
    def _assert_ready(self, model: str) -> None:
        if not self._enable_real:
            raise ProviderError(
                ProviderErrorCode.CONFIG_ERROR,
                "real model calls disabled; set AI_TEAM_MODEL_ENABLE_REAL=true",
                provider=self.provider_name,
                model=model,
            )
        if not self._api_key:
            raise ProviderError(
                ProviderErrorCode.CONFIG_ERROR,
                "missing API key (AI_TEAM_MODEL_API_KEY)",
                provider=self.provider_name,
                model=model,
            )
        if not self._base_url:
            raise ProviderError(
                ProviderErrorCode.CONFIG_ERROR,
                "missing base url (AI_TEAM_MODEL_BASE_URL)",
                provider=self.provider_name,
                model=model,
            )

    def _assert_url_allowed(self, url: str) -> None:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme != "https":
            if self._allow_local and scheme in ("http",):
                pass  # 本地模型模式：独立开关显式启用（7.3）
            else:
                raise ProviderError(
                    ProviderErrorCode.CONFIG_ERROR,
                    "base url must use https://",
                    provider=self.provider_name,
                    model="",
                )
        if parsed.hostname:
            reason = _blocked_host_reason(parsed.hostname)
            if reason and not self._allow_local:
                raise ProviderError(
                    ProviderErrorCode.CONFIG_ERROR,
                    f"base url rejected: {reason}",
                    provider=self.provider_name,
                    model="",
                )

    def _parse_success(self, request: ModelRequest, resp: httpx.Response) -> ModelResponse:
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            raise ProviderError(
                ProviderErrorCode.MALFORMED_RESPONSE,
                "provider returned non-JSON response",
                provider=self.provider_name,
                model=request.model,
            ) from None
        try:
            choices = data["choices"]
            if not choices:
                raise KeyError("empty choices")
            raw_text = choices[0].get("message", {}).get("content", "") or ""
            finish_reason = choices[0].get("finish_reason")
            usage = data.get("usage")
            if usage:
                input_tokens = int(usage.get("prompt_tokens", 0))
                output_tokens = int(usage.get("completion_tokens", 0))
                total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens))
            else:
                # usage 缺失：按估算记账（10.2），防止预算绕过；不伪造价格
                input_tokens = max(1, sum(len(m.get("content", "")) for m in request.messages) // 4)
                output_tokens = request.max_output_tokens or 0
                total_tokens = input_tokens + output_tokens
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                ProviderErrorCode.MALFORMED_RESPONSE,
                "malformed chat completion response",
                provider=self.provider_name,
                model=request.model,
            ) from exc
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=request.model,
            raw_text=raw_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost=None,  # 价格由价格表计算（10.3）
            latency_ms=0,
            finish_reason=finish_reason,
            provider_request_id=str(data.get("id", "")),
            retry_count=0,
        )
