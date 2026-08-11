from __future__ import annotations

from collections import deque

from app.voice.models import VoiceTurn


class ConversationSession:
    """Short-lived working context with both turn and approximate-token bounds."""

    def __init__(self, max_turns: int = 12, max_tokens: int = 3000) -> None:
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self._turns: deque[VoiceTurn] = deque(maxlen=max_turns)

    def add(self, turn: VoiceTurn) -> None:
        self._turns.append(turn)
        while self._estimated_tokens() > self.max_tokens and len(self._turns) > 1:
            self._turns.popleft()

    def turns(self) -> list[VoiceTurn]:
        return list(self._turns)

    def context(self, limit: int = 4) -> list[dict[str, str]]:
        return [
            {"user": item.user_text, "assistant": item.assistant_text[:1000]}
            for item in list(self._turns)[-limit:]
        ]

    def resize(self, max_turns: int, max_tokens: int) -> None:
        existing = list(self._turns)
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self._turns = deque(existing[-max_turns:], maxlen=max_turns)
        while self._estimated_tokens() > self.max_tokens and len(self._turns) > 1:
            self._turns.popleft()

    def _estimated_tokens(self) -> int:
        characters = sum(
            len(item.user_text) + len(item.assistant_text) for item in self._turns
        )
        return (characters + 3) // 4
