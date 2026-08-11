from __future__ import annotations

import re
import uuid

from app.desktop_vision.models import (
    ConfidenceBand,
    DesktopObservation,
    GroundingCandidate,
    GroundingStatus,
    VisualElement,
    VisualGrounding,
)


class GroundingResolver:
    """Deterministic spatial/text resolver. Screen text is matching data, never an instruction."""

    AMBIGUITY_GAP = 0.06

    def resolve(self, observation: DesktopObservation, target: str) -> VisualGrounding:
        normalized = target.strip().lower()
        if any(
            term in normalized
            for term in ("password", "credential", "private key", "api key", "密码", "凭据", "私钥")
        ):
            return self._unresolved(
                observation,
                target,
                [],
                "Sensitive credential targets are forbidden for visual action.",
            )
        action_target = any(
            term in normalized
            for term in ("click", "open", "press", "select", "点击", "打开", "按", "选择")
        )
        candidates: list[tuple[VisualElement, float]] = []
        for element in observation.visual_elements:
            if element.sensitive or (action_target and not element.clickable_estimate):
                continue
            score = self._score(element, normalized, observation)
            if score >= 0.45:
                candidates.append((element, score))
        ordinal = self._ordinal_index(normalized)
        if ordinal is not None and candidates:
            ordered = sorted(candidates, key=lambda item: (item[0].bounds.top, item[0].bounds.left))
            candidates = [
                (
                    element,
                    round(
                        min(0.99, max(0, score + (0.12 if index == ordinal else -0.04))),
                        3,
                    ),
                )
                for index, (element, score) in enumerate(ordered)
            ]
        candidates.sort(key=lambda item: item[1], reverse=True)
        public = [
            GroundingCandidate(
                visual_element_id=element.visual_element_id,
                label=element.label or element.element_type,
                bounds=element.bounds,
                score=score,
                source=element.source,
            )
            for element, score in candidates[:5]
        ]
        if not candidates:
            return self._unresolved(observation, target, public, "No confident target matched.")
        selected, confidence = candidates[0]
        if len(candidates) > 1 and candidates[1][1] >= 0.75:
            sameish = abs(confidence - candidates[1][1]) < self.AMBIGUITY_GAP
            strong_spatial = any(
                hint in normalized
                for hint in ("far right", "rightmost", "far left", "leftmost", "最右", "最左")
            )
            core = self._target_core(normalized)
            selected_exact = self._normalize_label(selected.label or selected.text) == core
            second = candidates[1][0]
            second_label = self._normalize_label(second.label or second.text)
            second_exact = second_label == core
            exact_disambiguates = selected_exact and not second_exact and core not in second_label
            if sameish and not strong_spatial and not exact_disambiguates:
                return VisualGrounding(
                    grounding_id=f"ground_{uuid.uuid4().hex[:18]}",
                    observation_id=observation.observation_id,
                    capture_id=observation.capture_id,
                    target_description=target,
                    candidate_elements=public,
                    confidence=confidence,
                    confidence_band=self.band(confidence),
                    reason_summary_safe=(
                        "Multiple visible controls match the requested description."
                    ),
                    status=GroundingStatus.NEEDS_CLARIFICATION,
                    clarification_prompt=(
                        "I am not sure which control you mean. "
                        "Please choose a highlighted candidate."
                    ),
                )
        band = self.band(confidence)
        if band is ConfidenceBand.LOW:
            return self._unresolved(
                observation,
                target,
                public,
                "The best visual match is below the safe confidence threshold.",
                confidence=confidence,
            )
        accessibility_match = selected.accessibility_element_id is not None
        reason = self._safe_reason(selected, normalized)
        return VisualGrounding(
            grounding_id=f"ground_{uuid.uuid4().hex[:18]}",
            observation_id=observation.observation_id,
            capture_id=observation.capture_id,
            target_description=target,
            candidate_elements=public,
            selected_element=selected,
            selected_bounds=selected.bounds,
            confidence=confidence,
            confidence_band=band,
            reason_summary_safe=reason,
            accessibility_match=accessibility_match,
            requires_coordinate_fallback=not accessibility_match,
            status=GroundingStatus.RESOLVED,
        )

    @staticmethod
    def band(confidence: float) -> ConfidenceBand:
        if confidence >= 0.9:
            return ConfidenceBand.HIGH
        if confidence >= 0.75:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.LOW

    def _score(
        self,
        element: VisualElement,
        target: str,
        observation: DesktopObservation,
    ) -> float:
        searchable = (
            f"{element.label} {element.text} {element.icon_hint} {element.element_type} "
            f"{element.attributes.get('visual_label', '')}"
        ).lower()
        base = {
            "accessibility": 0.64,
            "accessibility_vision_fusion": 0.7,
            "local_deterministic_cv": 0.55,
            "external_multimodal": 0.6,
        }.get(element.source, 0.52)
        stop_words = {"click", "the", "button", "please", "点击", "那个", "按钮", "一下"}
        words = [
            part
            for part in re.split(r"[^\w\u4e00-\u9fff]+", target)
            if len(part) > 1 and part not in stop_words
        ]
        matched = sum(word in searchable for word in words)
        if words:
            base += min(0.16, matched / len(words) * 0.16)
            if matched == len(words):
                base += 0.06
        semantic_label = (element.label or element.text).strip().lower()
        if len(semantic_label) >= 2 and semantic_label in target:
            base += 0.16
        target_core = self._target_core(target)
        if semantic_label and self._normalize_label(semantic_label) == target_core:
            base += 0.12
        aliases = {
            "blue": ("blue", "蓝"),
            "orange": ("orange", "橙"),
            "green": ("green", "绿"),
            "red": ("red", "红"),
            "settings": ("settings", "setting", "gear", "设置", "齿轮"),
            "save": ("save", "保存"),
            "confirm": ("confirm", "确认"),
            "pause": ("pause", "暂停"),
            "refresh": ("refresh", "刷新"),
        }
        for hints in aliases.values():
            requested = any(hint in target for hint in hints)
            matched_alias = any(hint in searchable for hint in hints)
            if requested and matched_alias:
                base += 0.09
            elif requested:
                base -= 0.22
        center_x = (element.bounds.left + element.bounds.right) / 2
        center_y = (element.bounds.top + element.bounds.bottom) / 2
        screen = observation.capture_bounds
        relative_x = (center_x - screen.left) / max(screen.width, 1)
        relative_y = (center_y - screen.top) / max(screen.height, 1)
        if any(hint in target for hint in ("right", "右", "最右")):
            base += 0.09 if relative_x >= 0.58 else -0.08
        if any(hint in target for hint in ("left", "左", "最左")):
            base += 0.09 if relative_x <= 0.42 else -0.08
        if any(hint in target for hint in ("bottom", "下", "底")):
            base += 0.07 if relative_y >= 0.58 else -0.06
        if any(hint in target for hint in ("top", "上", "顶部")):
            base += 0.07 if relative_y <= 0.42 else -0.06
        if element.clickable_estimate:
            base += 0.04
        base += max(0, element.confidence - 0.75) * 0.28
        return round(min(0.99, max(0, base)), 3)

    @staticmethod
    def _target_core(target: str) -> str:
        core = target
        for token in (
            "please",
            "button",
            "click",
            "open",
            "press",
            "select",
            "找到",
            "按钮",
            "点击",
            "打开",
            "选择",
            "那个",
        ):
            core = core.replace(token, "")
        return "".join(core.split())

    @staticmethod
    def _ordinal_index(target: str) -> int | None:
        hints = {
            0: ("first", "1st", "第一个", "第一项"),
            1: ("second", "2nd", "第二个", "第二项"),
            2: ("third", "3rd", "第三个", "第三项"),
        }
        for index, values in hints.items():
            if any(value in target for value in values):
                return index
        return None

    @staticmethod
    def _normalize_label(label: str) -> str:
        return "".join(label.strip().lower().split())

    def _unresolved(
        self,
        observation: DesktopObservation,
        target: str,
        candidates: list[GroundingCandidate],
        reason: str,
        *,
        confidence: float = 0,
    ) -> VisualGrounding:
        return VisualGrounding(
            grounding_id=f"ground_{uuid.uuid4().hex[:18]}",
            observation_id=observation.observation_id,
            capture_id=observation.capture_id,
            target_description=target,
            candidate_elements=candidates,
            confidence=confidence,
            confidence_band=self.band(confidence),
            reason_summary_safe=reason,
            status=GroundingStatus.REJECTED,
            clarification_prompt="I am not sure which control you mean.",
        )

    @staticmethod
    def _safe_reason(selected: VisualElement, target: str) -> str:
        location = "the requested screen region" if any(
            term in target for term in ("left", "right", "top", "bottom", "左", "右", "上", "下")
        ) else "the visible controls"
        label = selected.label or selected.element_type
        return f'The target matches the visible "{label[:80]}" control and {location}.'
