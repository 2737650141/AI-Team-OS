from __future__ import annotations

import hashlib

from app.desktop_vision.models import VisionObservation, VisualElement
from app.windows_control.models import AccessibilityElement, Bounds


class ObservationFusion:
    """Fuses pixels with UIA while preserving Accessibility as the preferred identity."""

    CLICKABLE_TYPES = {
        "button",
        "checkbox",
        "combobox",
        "listitem",
        "menuitem",
        "tabitem",
        "hyperlink",
    }
    EDITABLE_TYPES = {"edit", "document", "textbox"}

    def fuse(
        self,
        accessibility: list[AccessibilityElement],
        vision: VisionObservation,
    ) -> list[VisualElement]:
        remaining = [item.model_copy(deep=True) for item in vision.elements]
        fused: list[VisualElement] = []
        for element in accessibility:
            uia_bounds = element.bounds
            if uia_bounds is None or uia_bounds.width <= 0 or uia_bounds.height <= 0:
                continue
            best = max(
                remaining,
                key=lambda candidate: self._overlap(uia_bounds, candidate.bounds),
                default=None,
            )
            overlap = self._overlap(uia_bounds, best.bounds) if best is not None else 0
            if best is not None and overlap >= 0.34:
                remaining.remove(best)
                fused.append(self._merge(element, best, overlap))
            else:
                fused.append(self._from_accessibility(element))
        fused.extend(remaining)
        return sorted(fused, key=lambda item: (item.bounds.top, item.bounds.left))

    def _merge(
        self,
        accessibility: AccessibilityElement,
        visual: VisualElement,
        overlap: float,
    ) -> VisualElement:
        control_type = accessibility.control_type.lower()
        label = accessibility.name or visual.label
        identity = hashlib.sha256(
            (accessibility.element_id + visual.visual_element_id).encode()
        ).hexdigest()[:18]
        return VisualElement(
            visual_element_id=f"fusion:{identity}",
            label=label,
            element_type=accessibility.control_type or visual.element_type,
            text=accessibility.name,
            icon_hint=visual.icon_hint,
            bounds=accessibility.bounds or visual.bounds,
            confidence=min(0.99, max(0.93, visual.confidence + overlap * 0.08)),
            source="accessibility_vision_fusion",
            accessibility_element_id=accessibility.element_id,
            clickable_estimate=control_type in self.CLICKABLE_TYPES,
            editable_estimate=control_type in self.EDITABLE_TYPES,
            sensitive=self._sensitive(accessibility),
            attributes={
                "pixel_overlap": round(overlap, 3),
                "visual_label": visual.label,
                "screen_content_trust": "untrusted",
            },
        )

    def _from_accessibility(self, element: AccessibilityElement) -> VisualElement:
        control_type = element.control_type.lower()
        return VisualElement(
            visual_element_id=f"access:{element.element_id.removeprefix('uia:')}",
            label=element.name,
            element_type=element.control_type or "accessibility_element",
            text=element.name,
            bounds=element.bounds,  # type: ignore[arg-type]
            confidence=0.94 if element.name or element.automation_id else 0.9,
            source="accessibility",
            accessibility_element_id=element.element_id,
            clickable_estimate=control_type in self.CLICKABLE_TYPES,
            editable_estimate=control_type in self.EDITABLE_TYPES,
            sensitive=self._sensitive(element),
            attributes={"automation_id": element.automation_id, "enabled": element.enabled},
        )

    @staticmethod
    def _overlap(first: Bounds, second: Bounds) -> float:
        first_area = first.width * first.height
        second_area = second.width * second.height
        if min(first_area, second_area) / max(first_area, second_area, 1) < 0.2:
            return 0.0
        left = max(first.left, second.left)
        top = max(first.top, second.top)
        right = min(first.right, second.right)
        bottom = min(first.bottom, second.bottom)
        if left >= right or top >= bottom:
            return 0.0
        intersection = (right - left) * (bottom - top)
        smaller = min(first_area, second_area)
        return intersection / max(smaller, 1)

    @staticmethod
    def _sensitive(element: AccessibilityElement) -> bool:
        metadata = f"{element.name} {element.control_type} {element.automation_id}".lower()
        return element.password or any(
            term in metadata for term in ("password", "credential", "private key", "密码", "凭据")
        )
