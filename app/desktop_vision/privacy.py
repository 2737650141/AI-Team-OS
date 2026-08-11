from __future__ import annotations

import hashlib

from PIL import Image, ImageDraw

from app.desktop_vision.models import CaptureMetadata, PrivacyRedaction, VisualElement
from app.windows_control.models import AccessibilityElement, Bounds


class ScreenPrivacyFilter:
    """Redacts secure UIA regions before an image can cross a provider boundary."""

    SENSITIVE_TERMS = {
        "password",
        "credential",
        "private key",
        "api key",
        "secret",
        "密码",
        "凭据",
        "私钥",
    }

    def detect(
        self,
        elements: list[AccessibilityElement],
        capture: CaptureMetadata,
    ) -> list[PrivacyRedaction]:
        redactions: list[PrivacyRedaction] = []
        for element in elements:
            text = f"{element.name} {element.control_type} {element.automation_id}".lower()
            sensitive = element.password or any(term in text for term in self.SENSITIVE_TERMS)
            if not sensitive or element.bounds is None:
                continue
            intersection = self._intersection(element.bounds, capture.bounds)
            if intersection is None:
                continue
            token = hashlib.sha256(
                f"{capture.capture_id}|{element.element_id}|{intersection}".encode("utf-8")
            ).hexdigest()[:16]
            redactions.append(
                PrivacyRedaction(
                    redaction_id=f"redact_{token}",
                    bounds=intersection,
                    reason="secure_accessibility_region",
                    accessibility_element_id=element.element_id,
                )
            )
        return redactions

    def apply(
        self,
        image: Image.Image,
        capture: CaptureMetadata,
        redactions: list[PrivacyRedaction],
    ) -> Image.Image:
        redacted = image.convert("RGB").copy()
        draw = ImageDraw.Draw(redacted)
        for item in redactions:
            local = (
                item.bounds.left - capture.bounds.left,
                item.bounds.top - capture.bounds.top,
                item.bounds.right - capture.bounds.left,
                item.bounds.bottom - capture.bounds.top,
            )
            draw.rectangle(local, fill=(20, 20, 24), outline=(240, 72, 72), width=3)
            if local[2] - local[0] > 80 and local[3] - local[1] > 20:
                draw.text((local[0] + 6, local[1] + 4), "REDACTED", fill=(255, 255, 255))
        return redacted

    def target_is_sensitive(
        self, target: VisualElement, redactions: list[PrivacyRedaction]
    ) -> bool:
        if target.sensitive:
            return True
        return any(
            self._intersection(target.bounds, item.bounds) is not None for item in redactions
        )

    @staticmethod
    def _intersection(first: Bounds, second: Bounds) -> Bounds | None:
        left = max(first.left, second.left)
        top = max(first.top, second.top)
        right = min(first.right, second.right)
        bottom = min(first.bottom, second.bottom)
        if left >= right or top >= bottom:
            return None
        return Bounds(left=left, top=top, right=right, bottom=bottom)
