from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalVoiceDecision:
    action: str
    matched: bool
    may_execute: bool


_PUNCTUATION = re.compile(r"[\s,，。.!！?？;；:：]+")
_COMMANDS = {
    "stop": {"stop", "stopnow", "停止", "立即停止", "停下", "住手"},
    "cancel": {"cancel", "cancelthat", "取消", "取消操作", "算了"},
    "pause": {"pause", "暂停", "先暂停", "等一下"},
    "resume": {"resume", "continue", "继续", "恢复"},
    "reject": {"reject", "rejectit", "拒绝", "拒绝操作", "不要批准"},
}
_APPROVE = {"approve", "approved", "批准", "同意批准", "确认执行"}


def normalize_command(text: str) -> str:
    return _PUNCTUATION.sub("", text.strip().lower())


def classify_local_command(text: str) -> LocalVoiceDecision:
    """Exact matching prevents longer negated phrases from becoming local actions."""
    normalized = normalize_command(text)
    for action, phrases in _COMMANDS.items():
        if normalized in phrases:
            return LocalVoiceDecision(action=action, matched=True, may_execute=True)
    if normalized in _APPROVE:
        return LocalVoiceDecision(
            action="approval_denied_by_voice", matched=True, may_execute=False
        )
    return LocalVoiceDecision(action="forward", matched=False, may_execute=True)
