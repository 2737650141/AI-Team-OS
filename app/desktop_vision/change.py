from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


class ScreenChangeDetector:
    """Deterministic, bounded visual change score for post-action verification."""

    def compare(self, before: Image.Image, after: Image.Image) -> float:
        first = self._normalized(before)
        second = self._normalized(after)
        difference = cv2.absdiff(first, second)
        changed = np.count_nonzero(difference > 18)
        return min(1.0, float(changed) / max(difference.size, 1))

    @staticmethod
    def _normalized(image: Image.Image) -> np.ndarray:
        rgb = np.asarray(image.convert("RGB"))
        return cv2.resize(rgb, (320, 180), interpolation=cv2.INTER_AREA)
