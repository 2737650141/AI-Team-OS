"""ModelRouter（005 八）：确定性角色模型路由。

- 角色不能自行选择模型（8.1）。
- 任务级覆盖来自用户/API 配置，经过允许模型列表校验，写入审计（8.2）。
- 模型名称不能注入任意 Provider URL（路由只产出模型名，URL 由 Provider 配置决定）。
- fallback 由 Router 确定性执行（12.1），模型不可自行调用备用模型。
"""

from __future__ import annotations

from app.core.config import AppSettings, ModelRouteSettings
from app.gateway.audit import AuditLog


class ModelRouter:
    def __init__(
        self,
        settings: ModelRouteSettings,
        audit: AuditLog | None = None,
        task_id: str = "",
        overrides: dict[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._audit = audit
        self._task_id = task_id
        # 任务级覆盖（005 8.2）：构造时校验并存储，后续 resolve 自动生效
        self._overrides: dict[str, str] = {}
        for role, model in (overrides or {}).items():
            self.resolve(role, overrides={role: model})  # 触发白名单校验 + 审计
            self._overrides[role] = model

    def resolve(self, role_type: str, overrides: dict[str, str] | None = None) -> str:
        """按角色解析模型；任务级覆盖经过允许列表校验（8.2）。"""
        merged = overrides or self._overrides
        if merged and role_type in merged:
            candidate = merged[role_type]
            if candidate not in self._settings.allowed_models:
                raise ValueError(
                    f"model override rejected: {candidate!r} not in allowed models "
                    f"{self._settings.allowed_models}"
                )
            if self._audit and candidate != self._settings.role_defaults.get(role_type):
                self._audit.entry(
                    "model_override",
                    task_id=self._task_id,
                    role=role_type,
                    model=candidate,
                )
            return candidate
        return self._settings.role_defaults.get(role_type, "")

    def fallback(self, role_type: str, current_model: str) -> str | None:
        """降级（12.1）：按 fallback_models 顺序返回备用模型；无则 None。"""
        for candidate in self._settings.fallback_models:
            if candidate != current_model:
                if self._audit:
                    self._audit.entry(
                        "model_fallback",
                        task_id=self._task_id,
                        role=role_type,
                        from_model=current_model,
                        to_model=candidate,
                    )
                return candidate
        return None

    def reviewer_isolated(self) -> bool:
        """Reviewer 与 Researcher 使用不同模型（8.3，非强制默认建议）。"""
        return self._settings.role_defaults.get("reviewer", "") != self._settings.role_defaults.get(
            "researcher", ""
        ) and bool(self._settings.role_defaults.get("reviewer"))


def build_router(
    settings: AppSettings,
    audit: AuditLog | None = None,
    task_id: str = "",
    overrides: dict[str, str] | None = None,
) -> ModelRouter:
    return ModelRouter(settings.routing, audit=audit, task_id=task_id, overrides=overrides)
