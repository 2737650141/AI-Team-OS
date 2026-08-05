"""ResumePayload：恢复值 Schema（003-A 三）。

背景：langgraph 1.2.10 中 `Command(resume=None)` 会触发上游缺陷
（`UnboundLocalError: cannot access local variable 'resume_is_map'`，
见 docs/adr/0001-resume-payload-compatibility.md 与 M0_M1_EVIDENCE §5）。
本项目恢复接口不允许以 None 作为恢复值，统一使用本 Schema。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResumePayload(BaseModel):
    """恢复值。action 为 str（字段层拒绝 None），恢复前经 Schema 校验。"""

    action: str = Field(default="continue", min_length=1)
    note: str | None = None
