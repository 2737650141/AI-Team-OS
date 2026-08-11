from __future__ import annotations

import hashlib
import uuid

import cv2
import numpy as np
from PIL import Image

from app.desktop_vision.models import CaptureMetadata, VisionObservation, VisualElement
from app.windows_control.models import Bounds


class LocalVisualAnalyzer:
    """Bounded deterministic CV; no OCR, model weights, network, or instruction following."""

    MIN_AREA = 180
    MAX_ELEMENTS = 80

    def analyze(self, image: Image.Image, capture: CaptureMetadata) -> VisionObservation:
        rgb = np.asarray(image.convert("RGB"))
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        mask = np.where((saturation >= 105) & (value >= 70), 255, 0).astype(np.uint8)
        kernel = np.ones((3, 3), np.uint8)
        closed_mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        contours, _hierarchy = cv2.findContours(
            closed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        elements: list[VisualElement] = []
        image_area = max(image.width * image.height, 1)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
            area = float(cv2.contourArea(contour))
            if area < self.MIN_AREA or area > image_area * 0.35:
                continue
            x, y, width, height = cv2.boundingRect(contour)
            if width < 12 or height < 12:
                continue
            fill_ratio = area / max(width * height, 1)
            if fill_ratio < 0.42:
                continue
            region = rgb[y : y + height, x : x + width]
            mean_values = region.reshape(-1, 3).mean(axis=0)
            mean = (int(mean_values[0]), int(mean_values[1]), int(mean_values[2]))
            label, kind, icon, colour_confidence = self._classify(mean, width, height, fill_ratio)
            absolute = Bounds(
                left=capture.bounds.left + x,
                top=capture.bounds.top + y,
                right=capture.bounds.left + x + width,
                bottom=capture.bounds.top + y + height,
            )
            identity = hashlib.sha256(
                f"{capture.capture_id}|{absolute}|{label}".encode("utf-8")
            ).hexdigest()[:18]
            elements.append(
                VisualElement(
                    visual_element_id=f"cv:{identity}",
                    label=label,
                    element_type=kind,
                    icon_hint=icon,
                    bounds=absolute,
                    confidence=min(0.89, 0.68 + fill_ratio * 0.14 + colour_confidence),
                    source="local_deterministic_cv",
                    clickable_estimate=kind in {"button", "icon_button"},
                    attributes={
                        "mean_rgb": list(mean),
                        "fill_ratio": round(fill_ratio, 3),
                        "screen_content_trust": "untrusted",
                    },
                )
            )
            if len(elements) >= self.MAX_ELEMENTS:
                break
        confidence = sum(item.confidence for item in elements) / len(elements) if elements else 0
        return VisionObservation(
            vision_observation_id=f"vision_{uuid.uuid4().hex[:18]}",
            capture_id=capture.capture_id,
            elements=sorted(elements, key=lambda item: (item.bounds.top, item.bounds.left)),
            summary=f"Local deterministic CV detected {len(elements)} coloured regions.",
            confidence=min(confidence, 0.89),
        )

    @staticmethod
    def _classify(
        mean: tuple[int, int, int], width: int, height: int, fill_ratio: float
    ) -> tuple[str, str, str, float]:
        red, green, blue = mean
        if blue > red * 1.2 and blue > green * 1.08:
            return "blue button", "button", "", 0.06
        if green > red * 1.15 and green > blue * 1.05:
            return "green button", "button", "", 0.05
        if red > 180 and 80 < green < 200 and blue < 90:
            return "orange moving target", "button", "", 0.06
        if red > 150 and blue > 110 and green < min(red, blue) * 0.78:
            kind = "icon_button" if abs(width - height) <= max(width, height) * 0.35 else "button"
            label = "settings gear" if kind == "icon_button" else "magenta button"
            icon = "settings" if kind == "icon_button" else ""
            return label, kind, icon, 0.07
        if red > green * 1.25 and red > blue * 1.25:
            return "danger button", "button", "delete", 0.05
        if abs(width - height) <= max(width, height) * 0.25 and fill_ratio < 0.75:
            return "icon", "icon_button", "unknown", 0.02
        return "visual control", "button", "", 0.0
