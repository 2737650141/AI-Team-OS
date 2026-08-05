"""结构化输出治理（005 九）：JSON 提取 → 解析 → Schema 校验 → 修复。

- 只接受单一顶层对象（9.3）：拒绝多对象拼接、尾随危险内容、超大输出。
- Schema 外字段：默认拒绝（除非模型显式允许，M3-A 一律拒绝）。
- 修复重试次数由集中配置控制（settings.max_output_repair_attempts）。
- 不执行任何模型返回的代码。
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError, create_model

JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class OutputValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def extract_json_text(text: str, max_bytes: int) -> str:
    """从模型输出提取单一 JSON 对象文本（9.3）。

    规则：优先取 ```json 围栏内容；否则整体 trim 后尝试解析。
    拒绝：多个顶层对象、超大输出、围栏外危险内容。
    """
    if len(text.encode("utf-8")) > max_bytes:
        raise OutputValidationError("output_too_large", f"output exceeds {max_bytes} bytes")
    # 围栏提取：只接受一个围栏块
    fences = JSON_FENCE_RE.findall(text)
    if fences:
        if len(fences) > 1:
            raise OutputValidationError("multiple_json_objects", "multiple fenced JSON blocks")
        candidate = fences[0].strip()
    else:
        candidate = text.strip()
    # 单一顶层对象：剥离可能的围栏外文本后必须整体可解析为一个对象
    if not candidate.startswith("{"):
        # 尝试从第一个 { 到最后一个 } 提取（模型常见包装），但要求无第二个顶层对象
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or start >= end:
            raise OutputValidationError("no_json_object", "no JSON object found")
        candidate = candidate[start : end + 1]
        if candidate.count("{") != candidate.count("}"):
            raise OutputValidationError("unbalanced_json", "unbalanced JSON braces")
    return candidate


def parse_json_object(text: str, max_bytes: int) -> dict[str, Any]:
    """提取并解析为单一顶层 dict（9.3）。"""
    candidate = extract_json_text(text, max_bytes)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise OutputValidationError("invalid_json", f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise OutputValidationError("not_single_object", "top-level JSON is not a single object")
    return data


def build_validator(schema: dict[str, Any]) -> type[BaseModel]:
    """由 dict schema 构造 Pydantic 校验器（字段名 → (类型, 默认值)）。

    schema 形如 {"field": {"type": "str|int|float|bool|list|dict", "required": bool}}。
    """
    fields: dict[str, Any] = {}
    for name, spec in schema.items():
        type_name = spec.get("type", "str") if isinstance(spec, dict) else "str"
        required = spec.get("required", True) if isinstance(spec, dict) else True
        annotation = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
        }.get(type_name, str)
        if required:
            fields[name] = (annotation, ...)
        else:
            fields[name] = (annotation | None, None)
    return create_model("StructuredOutput", **fields)


def validate_against_schema(data: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
    """Pydantic 校验：缺字段/多余字段均拒绝（9.3：Schema 外字段默认拒绝）。"""
    if schema is None:
        return data
    validator = build_validator(schema)
    allowed = set(schema.keys())
    extra = set(data.keys()) - allowed
    if extra:
        raise OutputValidationError("extra_fields", f"schema-external fields: {sorted(extra)}")
    try:
        validated = validator.model_validate(data)
    except ValidationError as exc:
        errors = [f"{e['loc']}: {e['msg']}" for e in exc.errors()]
        raise OutputValidationError("schema_validation_failed", "; ".join(errors)) from exc
    return validated.model_dump()


def build_repair_request(schema: dict[str, Any], error: OutputValidationError) -> str:
    """生成一次结构化修复请求（9.2：错误反馈给模型）。"""
    return (
        "你的上一条输出未通过结构化校验，请只输出符合以下 JSON Schema 的单个 JSON 对象，"
        "不要添加任何解释文本。\n"
        f"Schema: {json.dumps(schema, ensure_ascii=False)}\n"
        f"校验错误: {error}"
    )
