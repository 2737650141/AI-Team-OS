from __future__ import annotations

from enum import StrEnum


class RunKind(StrEnum):
    USER_TASK = "user_task"
    CONVERSATION = "conversation"
    DIAGNOSTIC = "diagnostic"
    SYSTEM = "system"


_CONVERSATION_PROMPTS = {
    "你好",
    "你可以干什么",
    "你能做什么",
    "你是谁",
    "介绍一下你自己",
    "hello",
    "hi",
    "who are you",
    "what can you do",
}


def classify_run_kind(goal: str) -> RunKind:
    """Classify only side-effect-free conversational intents."""
    text = (goal or "").strip().lower().rstrip("?？!！。")
    return RunKind.CONVERSATION if text in _CONVERSATION_PROMPTS else RunKind.USER_TASK


def effective_run_kind(stored: str, goal: str) -> RunKind:
    """Classify legacy records without rewriting or deleting checkpoints."""
    if (goal or "").strip().lower() == "reply with exactly: ok":
        return RunKind.DIAGNOSTIC
    try:
        kind = RunKind(stored)
    except ValueError:
        kind = RunKind.USER_TASK
    if kind is RunKind.USER_TASK:
        return classify_run_kind(goal)
    return kind
