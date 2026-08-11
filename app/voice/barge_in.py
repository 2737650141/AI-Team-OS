from __future__ import annotations

from app.voice.adapters import SpeechSynthesizer


class BargeInController:
    """Local interruption boundary; it never waits for an LLM."""

    def __init__(self, synthesizer: SpeechSynthesizer) -> None:
        self.synthesizer = synthesizer
        self.interruptions = 0

    def interrupt(self) -> None:
        self.synthesizer.stop()
        self.interruptions += 1
