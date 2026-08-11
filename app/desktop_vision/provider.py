from __future__ import annotations

from typing import Protocol

from PIL import Image

from app.desktop_vision.models import (
    CaptureMetadata,
    VisionCapability,
    VisionObservation,
    VisionSettings,
)


class VisionProvider(Protocol):
    def analyze_screen(
        self, image: Image.Image, capture: CaptureMetadata, *, prompt: str
    ) -> VisionObservation: ...

    def locate_element(
        self, image: Image.Image, capture: CaptureMetadata, *, target: str
    ) -> VisionObservation: ...


class VisionPolicyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VisionCapabilityRegistry:
    """Capability and consent registry; it never guesses image support from a model name."""

    def __init__(self) -> None:
        self.settings = VisionSettings()
        self._capabilities: dict[tuple[str, str], VisionCapability] = {}
        self._providers: dict[str, VisionProvider] = {}
        self.register_capability(
            VisionCapability(
                provider="deepseek",
                model="deepseek-v4-flash",
                supports_image_input=False,
                local=False,
                verified=True,
            )
        )

    def register_capability(self, capability: VisionCapability) -> None:
        self._capabilities[(capability.provider, capability.model)] = capability

    def register_provider(self, provider: str, adapter: VisionProvider) -> None:
        self._providers[provider] = adapter

    def configure_route(self, provider: str | None, model: str | None) -> VisionSettings:
        if bool(provider) != bool(model):
            raise VisionPolicyError(
                "invalid_vision_route", "Provider and model must be set together"
            )
        if provider and model:
            capability = self.capability(provider, model)
            if (
                capability is None
                or not capability.supports_image_input
                or not capability.verified
            ):
                raise VisionPolicyError(
                    "image_input_unsupported", "Selected model has no verified image capability"
                )
        self.settings.route_provider = provider
        self.settings.route_model = model
        return self.settings.model_copy(deep=True)

    def set_external_processing(
        self, allowed: bool, *, consent_acknowledged: bool = False
    ) -> VisionSettings:
        if allowed and not consent_acknowledged:
            raise VisionPolicyError(
                "vision_consent_required",
                "Explicit screenshot-processing consent is required",
            )
        if allowed:
            provider = self.settings.route_provider
            model = self.settings.route_model
            capability = self.capability(provider, model) if provider and model else None
            if (
                capability is None
                or not capability.supports_image_input
                or not capability.verified
                or provider not in self._providers
            ):
                raise VisionPolicyError(
                    "vision_model_not_configured",
                    "A verified image-capable provider adapter is required",
                )
        self.settings.allow_external_processing = allowed
        self.settings.consent_acknowledged = allowed and consent_acknowledged
        return self.settings.model_copy(deep=True)

    def capability(self, provider: str, model: str) -> VisionCapability | None:
        item = self._capabilities.get((provider, model))
        return item.model_copy(deep=True) if item else None

    def external_adapter(self) -> tuple[VisionProvider, VisionCapability]:
        if not self.settings.allow_external_processing:
            raise VisionPolicyError("external_vision_disabled", "External vision is disabled")
        provider = self.settings.route_provider
        model = self.settings.route_model
        if not provider or not model:
            raise VisionPolicyError("vision_model_not_configured", "Vision model is not configured")
        capability = self.capability(provider, model)
        adapter = self._providers.get(provider)
        if capability is None or not capability.supports_image_input or adapter is None:
            raise VisionPolicyError(
                "vision_model_not_configured", "A verified vision adapter is not configured"
            )
        return adapter, capability

    def status(self) -> dict[str, object]:
        provider = self.settings.route_provider
        model = self.settings.route_model
        capability = self.capability(provider, model) if provider and model else None
        return {
            "provider": provider or "NOT_CONFIGURED",
            "model": model or "NOT_CONFIGURED",
            "supports_image_input": bool(capability and capability.supports_image_input),
            "external_processing": self.settings.allow_external_processing,
            "consent_acknowledged": self.settings.consent_acknowledged,
            "multimodal_status": (
                "VALIDATED"
                if capability and capability.supports_image_input and capability.verified
                else "NOT_CONFIGURED"
            ),
            "text_model": {
                "provider": "DeepSeek Official",
                "model": "deepseek-v4-flash",
                "real": True,
            },
        }
