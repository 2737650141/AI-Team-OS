"""集中式配置系统（005 五）：AppSettings / ModelProviderSettings / ModelRouteSettings。

- 环境变量前缀 AI_TEAM_MODEL_*（005 5.1），API Key 只从环境变量读取（5.2）。
- 配置优先级：运行参数 → 环境变量 → 默认值（5.3）。
- 密钥规则：API Key 不进入 RuntimeState / Checkpoint / messages / 审计日志 / 异常信息 /
  API 响应 / trace；Agent 不可读取（005 5.2）。
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "AI_TEAM_MODEL_"


class ModelProviderSettings(BaseSettings):
    """真实模型 Provider 配置（005 5.1 全部环境变量）。"""

    # API Key 只从环境变量读取；显式禁用 .env 文件加载（005 5.2）
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore", env_file=None)

    provider: str = "openai_compatible"  # AI_TEAM_MODEL_PROVIDER
    base_url: str = ""  # AI_TEAM_MODEL_BASE_URL（仅 https://，SSRF 校验见 provider）
    api_key: str = ""  # AI_TEAM_MODEL_API_KEY（只从环境变量）
    default_model: str = ""  # AI_TEAM_MODEL_DEFAULT
    supervisor_model: str = ""  # AI_TEAM_MODEL_SUPERVISOR
    planner_model: str = ""  # AI_TEAM_MODEL_PLANNER
    researcher_model: str = ""  # AI_TEAM_MODEL_RESEARCHER
    reviewer_model: str = ""  # AI_TEAM_MODEL_REVIEWER
    executor_model: str = ""  # AI_TEAM_MODEL_EXECUTOR
    timeout_seconds: int = Field(default=60, gt=0)  # AI_TEAM_MODEL_TIMEOUT_SECONDS
    max_retries: int = Field(default=2, ge=0)  # AI_TEAM_MODEL_MAX_RETRIES
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)  # AI_TEAM_MODEL_TEMPERATURE
    max_output_tokens: int = Field(default=4096, gt=0)  # AI_TEAM_MODEL_MAX_OUTPUT_TOKENS
    enable_real: bool = False  # AI_TEAM_MODEL_ENABLE_REAL（真实调用必须显式开启，005 7.4）
    # 本地只读根目录（006 8.1）：AI_TEAM_ALLOWED_READ_ROOTS（分号分隔），默认空
    allowed_read_roots: str = ""


class ModelPrice(BaseModel):
    """价格表条目（005 10.3 集中配置，禁止散落硬编码）。"""

    provider: str
    model: str
    input_price_per_million: float
    output_price_per_million: float
    effective_from: str


# 集中价格表：价格未知的模型返回 None（estimated_cost=null，不伪造费用）
PRICING: list[ModelPrice] = [
    ModelPrice(
        provider="openai_compatible",
        model="placeholder-default",
        input_price_per_million=1.0,
        output_price_per_million=2.0,
        effective_from="2026-01-01",
    ),
    ModelPrice(
        provider="DeepSeek Official",
        model="deepseek-v4-flash",
        input_price_per_million=0.14,
        output_price_per_million=0.28,
        effective_from="2026-04-24",
    ),
]


def lookup_price(provider: str, model: str) -> ModelPrice | None:
    """按 provider+model 精确匹配价格；未知返回 None（005 10.3）。"""
    for p in PRICING:
        if p.provider == provider and p.model == model:
            return p
    return None


class ModelRouteSettings(BaseModel):
    """角色模型路由（005 八）：确定性配置决定，角色不能自行选择模型。"""

    role_defaults: dict[str, str] = Field(
        default_factory=lambda: {
            "supervisor": "",
            "planner": "",
            "researcher": "",
            "reviewer": "",
            "executor": "",
        }
    )
    allowed_models: list[str] = Field(default_factory=list)
    fallback_models: list[str] = Field(default_factory=list)


class AppSettings(BaseModel):
    """应用集中配置（005 五）。"""

    model: ModelProviderSettings = Field(default_factory=ModelProviderSettings)
    routing: ModelRouteSettings = Field(default_factory=ModelRouteSettings)
    # 结构化输出治理（005 九）
    max_json_output_bytes: int = Field(default=64 * 1024, gt=0)
    max_output_repair_attempts: int = Field(default=2, ge=0)
    # 重试（005 十一）
    retry_backoff_base_seconds: float = Field(default=0.5, gt=0)
    retry_max_delay_seconds: float = Field(default=8.0, gt=0)


def load_settings(env: dict[str, str] | None = None) -> AppSettings:
    """从环境变量构建设置（测试可注入 env dict，不读真实环境）。"""
    model = ModelProviderSettings()
    # 手动从 env 读取（支持注入），保留 BaseSettings 默认值语义
    prefix = ENV_PREFIX
    if env:
        for key, value in env.items():
            if key.startswith(prefix) and hasattr(model, key[len(prefix) :].lower()):
                setattr(
                    model,
                    key[len(prefix) :].lower(),
                    _coerce(model, key[len(prefix) :].lower(), value),
                )
    routing = ModelRouteSettings(
        role_defaults={
            "supervisor": model.supervisor_model or model.default_model,
            "planner": model.planner_model or model.default_model,
            "researcher": model.researcher_model or model.default_model,
            "reviewer": model.reviewer_model or model.default_model,
            "executor": model.executor_model or model.default_model,
        }
    )
    if model.default_model:
        routing.allowed_models = [model.default_model]
    if model.supervisor_model:
        routing.allowed_models.append(model.supervisor_model)
    if model.planner_model:
        routing.allowed_models.append(model.planner_model)
    if model.researcher_model:
        routing.allowed_models.append(model.researcher_model)
    if model.reviewer_model:
        routing.allowed_models.append(model.reviewer_model)
    routing.allowed_models = list(dict.fromkeys(routing.allowed_models))
    return AppSettings(model=model, routing=routing)


def _coerce(settings: BaseSettings, field: str, value: str):
    """按字段类型转换环境变量字符串（bool/int/float/str）。"""
    field_info = settings.model_fields[field]
    annotation = field_info.annotation
    if annotation is bool:
        return value.strip().lower() in ("1", "true", "yes", "on")
    if annotation is int:
        return int(value)
    if annotation is float:
        return float(value)
    return value


def allowed_read_roots(settings: AppSettings | None = None) -> list[Path]:
    """006 8.1：本地只读根目录（分号分隔环境变量），默认无。

    优先 AI_TEAM_ALLOWED_READ_ROOTS（006 语义，不经 MODEL 前缀），
    回退 settings.model.allowed_read_roots（AI_TEAM_MODEL_ALLOWED_READ_ROOTS）。
    """
    settings = settings or load_settings()
    raw = (
        os.environ.get("AI_TEAM_ALLOWED_READ_ROOTS", "").strip()
        or settings.model.allowed_read_roots.strip()
    )
    if not raw:
        return []
    return [Path(p.strip()) for p in raw.split(";") if p.strip()]
