from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


def empty_voice_latency() -> dict[str, float | None]:
    return {
        "wake_ms": None,
        "speech_end_ms": None,
        "asr_ms": None,
        "llm_ms": None,
        "tts_first_audio_ms": None,
        "end_to_end_ms": None,
    }


class VoiceState(StrEnum):
    IDLE = "idle"
    WAKE_LISTENING = "wake_listening"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    PAUSED = "paused"
    ERROR = "error"


class MicState(StrEnum):
    OFF = "MIC OFF"
    LISTENING = "MIC LISTENING"
    ACTIVE = "MIC ACTIVE"
    MUTED = "MIC MUTED"
    ERROR = "MIC ERROR"


class VoiceSettings(BaseModel):
    voice_enabled: bool = False
    microphone_enabled: bool = False
    wake_word_enabled: bool = False
    push_to_talk: bool = True
    input_device_id: int | None = None
    output_device_id: int | None = None
    language: Literal["auto", "zh", "en"] = "auto"
    whisper_executable: str = ""
    whisper_model: str = ""
    vad_model: str = ""
    wake_model: str = ""
    tts_voice: str = ""
    tts_rate: int = Field(default=0, ge=-10, le=10)
    max_record_seconds: int = Field(default=30, ge=1, le=120)
    max_session_turns: int = Field(default=12, ge=2, le=50)
    max_session_tokens: int = Field(default=3000, ge=256, le=20_000)
    conversation_mode: Literal["single", "conversation"] = "conversation"
    conversation_timeout_seconds: int = Field(default=30, ge=15, le=90)
    allow_external_speech_processing: bool = False


class AudioDevice(BaseModel):
    id: int
    name: str
    input_channels: int = 0
    output_channels: int = 0
    default_sample_rate: float
    is_default_input: bool = False
    is_default_output: bool = False


class TranscriptSegment(BaseModel):
    text: str
    started_ms: int = 0
    ended_ms: int = 0
    final: bool = True
    language: str = "unknown"
    confidence: float | None = None


class VoiceTurn(BaseModel):
    turn_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    user_text: str
    assistant_text: str = ""
    route: str = "supervisor"
    action: str = "forward"
    task_id: str | None = None


class VoiceSession(BaseModel):
    session_id: str
    active: bool = False
    mode: Literal["single", "conversation"] = "conversation"
    max_turns: int = 12
    max_tokens: int = 3000


class VoiceStatus(BaseModel):
    state: VoiceState = VoiceState.IDLE
    mic_state: MicState = MicState.OFF
    session_active: bool = False
    partial_transcript: str = ""
    final_transcript: str = ""
    error_code: str | None = None
    error_message: str | None = None
    input_device: str | None = None
    output_device: str | None = None
    asr_status: str = "NOT_CONFIGURED"
    wake_status: str = "DISABLED"
    tts_status: str = "AVAILABLE"
    raw_audio_persisted: bool = False
    local_command_priority: bool = True
    output_suppression: bool = True
    latency: dict[str, float | None] = Field(default_factory=empty_voice_latency)
    settings: VoiceSettings = Field(default_factory=VoiceSettings)
    turns: list[VoiceTurn] = Field(default_factory=list)
