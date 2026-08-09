"""005 18.2：OpenAI-compatible Provider Mock HTTP 测试（httpx MockTransport，不访问真实网络）。

覆盖：200 正常 / 401 / 403 / 404 / 429 / 500 / 超时 / 非 JSON / Usage 缺失 /
响应体超限 / 重定向到内网地址。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.gateway.contracts import (
    ModelRequest,
    ProviderError,
    ProviderErrorCode,
)
from app.gateway.openai_compatible import OpenAICompatibleProvider


def _request(model: str = "m1") -> ModelRequest:
    return ModelRequest(
        request_id="req-1",
        task_id="t",
        agent_id="a",
        role_type="planner",
        model=model,
        messages=[{"role": "user", "content": "hi"}],
        max_output_tokens=100,
    )


def _provider(handler, **kwargs) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    return OpenAICompatibleProvider(
        # 公网 IP 字面量：避免域名触发真实 DNS 解析（离线测试严格无网络）
        base_url="https://8.8.8.8/v1",
        api_key="sk-test",
        enable_real=True,
        transport=transport,
        **kwargs,
    )


def _ok_body(model: str = "m1") -> dict:
    return {
        "id": "chatcmpl-test",
        "choices": [
            {"message": {"content": '{"summary": "s", "claims": []}'}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        "model": model,
    }


def test_http_200_ok() -> None:
    provider = _provider(lambda req: httpx.Response(200, json=_ok_body()))
    resp = provider.generate(_request())
    assert resp.raw_text == '{"summary": "s", "claims": []}'
    assert resp.input_tokens == 12
    assert resp.output_tokens == 8
    assert resp.total_tokens == 20
    assert resp.provider == "openai_compatible"
    assert resp.model == "m1"
    assert resp.usage_available is True


def test_structured_request_enables_json_mode() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content))
        return httpx.Response(200, json=_ok_body())

    request = _request()
    request.response_schema = {"summary": {"type": "str"}}
    _provider(handler).generate(request)
    assert captured["response_format"] == {"type": "json_object"}
    assert "thinking" not in captured


def test_deepseek_structured_request_disables_default_thinking() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content))
        return httpx.Response(200, json=_ok_body())

    provider = _provider(handler)
    provider._base_url = "https://api.deepseek.com"  # noqa: SLF001
    provider._assert_url_allowed = lambda _url: None  # type: ignore[method-assign]  # noqa: SLF001
    request = _request()
    request.response_schema = {"summary": {"type": "str"}}
    provider.generate(request)
    assert captured["thinking"] == {"type": "disabled"}


def test_real_stream_is_consumed_once_and_records_latency() -> None:
    class OneShotStream(httpx.SyncByteStream):
        def __iter__(self):
            yield json.dumps(_ok_body("provider-returned-model")).encode()

    provider = _provider(lambda req: httpx.Response(200, stream=OneShotStream()))
    resp = provider.generate(_request("requested-model"))
    assert resp.model == "provider-returned-model"
    assert resp.latency_ms >= 1


def test_http_401_authentication() -> None:
    provider = _provider(lambda req: httpx.Response(401, text="unauthorized"))
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request())
    assert exc_info.value.code == ProviderErrorCode.AUTHENTICATION_ERROR


def test_http_403_permission() -> None:
    provider = _provider(lambda req: httpx.Response(403, text="forbidden"))
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request())
    assert exc_info.value.code == ProviderErrorCode.PERMISSION_ERROR


def test_http_404_model_not_found() -> None:
    provider = _provider(lambda req: httpx.Response(404, text="model not found"))
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request())
    assert exc_info.value.code == ProviderErrorCode.MODEL_NOT_FOUND


def test_http_429_rate_limited() -> None:
    provider = _provider(
        lambda req: httpx.Response(429, headers={"retry-after": "2"}, text="rate limited")
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request())
    assert exc_info.value.code == ProviderErrorCode.RATE_LIMITED
    assert exc_info.value.retryable is True


def test_http_500_provider_internal() -> None:
    provider = _provider(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request())
    assert exc_info.value.code == ProviderErrorCode.PROVIDER_INTERNAL_ERROR
    assert exc_info.value.retryable is True


def test_http_timeout() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=req)

    provider = _provider(handler)
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request())
    assert exc_info.value.code == ProviderErrorCode.TIMEOUT
    assert exc_info.value.retryable is True


def test_http_non_json_response() -> None:
    provider = _provider(lambda req: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request())
    assert exc_info.value.code == ProviderErrorCode.MALFORMED_RESPONSE


def test_usage_missing_tolerated() -> None:
    """Usage 缺失：按估算记账（10.2 防预算绕过），不伪造费用。"""
    body = _ok_body()
    del body["usage"]
    provider = _provider(lambda req: httpx.Response(200, json=body))
    resp = provider.generate(_request())
    assert resp.input_tokens >= 1  # 估算记账（messages 字符 /4）
    assert resp.output_tokens == 100  # 按 max_output_tokens 估算
    assert resp.estimated_cost is None  # 价格未知不伪造
    assert resp.usage_available is False


def test_response_body_too_large() -> None:
    """响应体超限：超大 body 由 max_read_bytes 限制（7.2）。"""
    big = '{"content": "' + "x" * (2 * 1024 * 1024) + '"}'

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=big)

    provider = _provider(handler)
    with pytest.raises(ProviderError):
        provider.generate(_request())


def test_redirect_to_internal_rejected() -> None:
    """重定向到内网地址：拒绝（7.3）。"""
    provider = _provider(
        lambda req: httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
        )
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request())
    assert exc_info.value.code == ProviderErrorCode.CONFIG_ERROR
    assert "redirect" in exc_info.value.safe_message


def test_authorization_header_not_logged() -> None:
    """Authorization 不进入日志（7.2）：请求头只有调用时构造，provider 不记录。"""
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers.get("authorization", ""))
        return httpx.Response(200, json=_ok_body())

    provider = _provider(handler)
    provider.generate(_request())
    assert seen == ["Bearer sk-test"]
    # 审计日志与 provider 状态不含 key
    assert "sk-test" not in json.dumps(provider.health_check().model_dump())
