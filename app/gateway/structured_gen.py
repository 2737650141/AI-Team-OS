"""结构化生成助手（005 9.2）：生成 → 提取/解析/Pydantic 校验 → 修复循环。

- 修复重试次数受集中配置控制（settings.max_output_repair_attempts），不得无限自我修复。
- 校验失败不写入正式状态（由调用方决定状态写入）。
- 每次修复请求把 Schema 错误反馈给模型（9.2 第 4 条）。
"""

from __future__ import annotations

from app.core.config import AppSettings
from app.core.output_governance import (
    OutputValidationError,
    build_repair_request,
    parse_json_object,
    validate_against_schema,
)
from app.gateway.contracts import ModelRequest, ProviderError, ProviderErrorCode
from app.gateway.model_gateway import ModelGateway


def generate_structured(
    gateway: ModelGateway,
    request: ModelRequest,
    schema: dict,
    settings: AppSettings,
    max_retries: int | None = None,
    sleep_fn=None,
) -> dict:
    """生成并校验结构化输出；失败时按修复上限重试；超限抛 SCHEMA_VALIDATION_FAILED。"""
    last_error: OutputValidationError | None = None
    for attempt in range(settings.max_output_repair_attempts + 1):
        resp = gateway.generate(
            request,
            max_retries=max_retries if max_retries is not None else settings.model.max_retries,
            sleep_fn=sleep_fn,
        )
        try:
            data = parse_json_object(resp.raw_text or "", settings.max_json_output_bytes)
            return validate_against_schema(data, schema)
        except OutputValidationError as exc:
            last_error = exc
            if attempt >= settings.max_output_repair_attempts:
                break
            # 保存脱敏错误摘要（9.2 第 1 条：不写正式状态），生成一次修复请求；
            # 回灌模型原始输出前截断（防模型回显密钥被持续发往第三方，LOW）
            request.messages = [
                *request.messages,
                {"role": "assistant", "content": (resp.raw_text or "")[:500]},
                {"role": "user", "content": build_repair_request(schema, exc)},
            ]
    raise ProviderError(
        ProviderErrorCode.SCHEMA_VALIDATION_FAILED,
        f"structured output failed after {settings.max_output_repair_attempts + 1} "
        f"attempts: {last_error}",
    )
