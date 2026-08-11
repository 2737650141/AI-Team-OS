from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.voice.adapters import (
    OpenWakeWordAdapter,
    SileroOnnxVadAdapter,
    SpeechRecognizer,
    SpeechSynthesizer,
    VoiceActivityDetector,
    WhisperCppAdapter,
    WindowsSapiSynthesizer,
)
from app.voice.audio import AudioCaptureService, WakeWordListener
from app.voice.barge_in import BargeInController
from app.voice.devices import AudioDeviceManager
from app.voice.models import MicState, VoiceSettings, VoiceState, VoiceStatus, VoiceTurn
from app.voice.safety import classify_local_command
from app.voice.session import ConversationSession
from app.voice.store import VoiceMetadataStore


class VoiceService:
    """Governed voice state machine. Only final transcripts can reach the supervisor."""

    def __init__(
        self,
        data_dir: Path,
        *,
        devices: AudioDeviceManager | None = None,
        capture: AudioCaptureService | None = None,
        wake_listener: WakeWordListener | None = None,
        recognizer: SpeechRecognizer | None = None,
        vad: VoiceActivityDetector | None = None,
        synthesizer: SpeechSynthesizer | None = None,
        supervisor: Callable[[str], dict[str, Any]] | None = None,
        local_action: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.store = VoiceMetadataStore(data_dir / "runtime" / "voice" / "voice.sqlite")
        self.settings = self.store.settings()
        self.devices = devices or AudioDeviceManager()
        self.capture = capture or AudioCaptureService()
        self.wake_listener = wake_listener or WakeWordListener()
        self._managed_recognizer = recognizer is None
        self.recognizer = recognizer or WhisperCppAdapter(
            self.settings.whisper_executable, self.settings.whisper_model
        )
        self.synthesizer = synthesizer or WindowsSapiSynthesizer()
        self._managed_vad = vad is None
        self.vad = vad or SileroOnnxVadAdapter(self.settings.vad_model)
        self.barge_in = BargeInController(self.synthesizer)
        self.wake = OpenWakeWordAdapter(self.settings.wake_model)
        self.supervisor = supervisor or (lambda text: {"status": "WAITING", "text": text})
        self.local_action = local_action or (
            lambda action: {"status": "accepted", "action": action}
        )
        self.state = VoiceState.IDLE
        self.mic_state = MicState.OFF
        self.session_active = False
        self.partial_transcript = ""
        self.final_transcript = ""
        self.error_code: str | None = None
        self.error_message: str | None = None
        self.conversation = ConversationSession(
            self.settings.max_session_turns, self.settings.max_session_tokens
        )
        self.latency: dict[str, float | None] = {
            "wake_ms": None,
            "speech_end_ms": None,
            "asr_ms": None,
            "llm_ms": None,
            "tts_first_audio_ms": None,
            "end_to_end_ms": None,
        }
        self._turn_started_at: float | None = None
        self._wake_monitor_stop = threading.Event()
        self._partial_stop = threading.Event()
        self._partial_worker: threading.Thread | None = None
        self._conversation_timer: threading.Timer | None = None
        self._lock = threading.RLock()

    def update_settings(self, settings: VoiceSettings) -> VoiceStatus:
        with self._lock:
            if not settings.voice_enabled:
                self.stop()
            if settings.wake_word_enabled and not settings.microphone_enabled:
                raise ValueError("wake word requires microphone_enabled")
            self.settings = self.store.save_settings(settings)
            self.conversation.resize(settings.max_session_turns, settings.max_session_tokens)
            if self._managed_recognizer:
                self.recognizer = WhisperCppAdapter(
                    settings.whisper_executable, settings.whisper_model
                )
            self.wake = OpenWakeWordAdapter(settings.wake_model)
            if self._managed_vad:
                self.vad = SileroOnnxVadAdapter(settings.vad_model)
            self._transition(VoiceState.IDLE, "settings_updated")
            return self.status()

    def start_session(self) -> VoiceStatus:
        with self._lock:
            if not self.settings.voice_enabled:
                return self._fail("VOICE_DISABLED", "Voice is disabled in Settings.")
            self.session_active = True
            self.error_code = self.error_message = None
            if self.settings.wake_word_enabled:
                if not self.wake.available():
                    self.session_active = False
                    return self._fail(
                        "WAKE_MODEL_NOT_CONFIGURED", "Wake word model is unavailable."
                    )
                try:
                    self._start_wake_listener()
                except RuntimeError as exc:
                    return self._device_failure(str(exc))
            else:
                self.mic_state = MicState.OFF
                self._transition(VoiceState.IDLE, "session_started")
            return self.status()

    def ptt_start(self) -> VoiceStatus:
        with self._lock:
            self._cancel_conversation_timeout()
            if not self.session_active:
                started = self.start_session()
                if started.state == VoiceState.ERROR:
                    return started
            if not self.settings.microphone_enabled:
                return self._fail("MICROPHONE_DISABLED", "Microphone access is disabled.")
            try:
                device = self.devices.validate_input(self.settings.input_device_id)
                self.wake_listener.stop()
                if self.state == VoiceState.SPEAKING:
                    self.barge_in.interrupt()
                    self._transition(VoiceState.INTERRUPTED, "barge_in")
                self.capture.start(device.id, self.settings.max_record_seconds)
                self.mic_state = MicState.LISTENING
                self._turn_started_at = time.perf_counter()
                self.partial_transcript = ""
                self.final_transcript = ""
                self._transition(VoiceState.LISTENING, "ptt_started")
                self._start_partial_transcription()
            except RuntimeError as exc:
                return self._device_failure(str(exc))
            return self.status()

    def update_partial(self, text: str) -> VoiceStatus:
        """UI-only streaming result. This never calls a model or an action gateway."""
        with self._lock:
            if self.state == VoiceState.LISTENING:
                self.partial_transcript = text[:2000]
            return self.status()

    def ptt_stop(self, *, execute: bool = True) -> VoiceStatus:
        with self._lock:
            if not self.capture.active:
                return self._fail("NOT_LISTENING", "Push-to-talk is not active.")
            self._partial_stop.set()
            pcm16 = self.capture.stop()
            self.mic_state = MicState.OFF
            duration_ms = int(len(pcm16) / 2 / 16_000 * 1000)
            self.latency["speech_end_ms"] = 0.0
            self._transition(
                VoiceState.TRANSCRIBING, "ptt_stopped", duration_ms=duration_ms
            )
        if not self.vad.contains_speech(pcm16):
            pcm16 = b""
            self.capture.clear()
            return self._fail("NO_SPEECH", "No speech was detected; no action was executed.")
        asr_started = time.perf_counter()
        try:
            segment = self.recognizer.transcribe(pcm16, self.settings.language)
        except RuntimeError as exc:
            pcm16 = b""
            self.capture.clear()
            code = {
                "ASR_NOT_CONFIGURED": "MODEL_NOT_LOADED",
                "ASR_INFERENCE_FAILED": "TRANSCRIPTION_FAILED",
                "EMPTY_AUDIO": "NO_SPEECH",
            }.get(str(exc), "TRANSCRIPTION_FAILED")
            return self._fail(code, "Speech recognition failed safely; no action was executed.")
        finally:
            self.latency["asr_ms"] = round((time.perf_counter() - asr_started) * 1000, 2)
            pcm16 = b""
            self.capture.clear()
        return self.submit_final(segment.text, execute=execute)

    def submit_final(self, text: str, *, execute: bool = True) -> VoiceStatus:
        """Accept ASR final text; local safety commands run before model invocation."""
        clean = text.strip()[:8000]
        with self._lock:
            if not clean:
                return self._fail("EMPTY_TRANSCRIPT", "No speech was recognized.")
            self.final_transcript = clean
            self.partial_transcript = ""
            decision = classify_local_command(clean)
            if not decision.matched:
                self._transition(VoiceState.THINKING, "supervisor_routing")

        task_id: str | None = None
        assistant_text = ""
        action = decision.action if decision.matched else "forward"
        if decision.matched:
            if decision.action == "approval_denied_by_voice":
                assistant_text = "Voice approval is not accepted. Use the visible approval control."
            elif execute:
                if decision.action in {"stop", "cancel", "pause", "reject"}:
                    self.synthesizer.stop()
                result = self.local_action(decision.action)
                task_id = result.get("task_id")
                assistant_text = str(
                    result.get("message", result.get("status", decision.action))
                )
            else:
                assistant_text = "Local command recognized; execution disabled for this test."
        elif execute:
            llm_started = time.perf_counter()
            try:
                result = self.supervisor(clean)
            except Exception as exc:  # provider details and tracebacks must not cross the voice API
                safe_error = str(getattr(exc, "safe_message", ""))
                detail = str(getattr(exc, "detail", ""))
                if "WAITING_FOR_PROVIDER_CREDENTIAL" in (safe_error or detail):
                    return self._fail(
                        "WAITING_FOR_PROVIDER_CREDENTIAL",
                        "Configure the Supervisor model route and credentials in AI Team settings.",
                    )
                return self._fail(
                    "SUPERVISOR_FAILED",
                    "The AI team could not accept this request; no voice approval was inferred.",
                )
            self.latency["llm_ms"] = round((time.perf_counter() - llm_started) * 1000, 2)
            task_id = result.get("run_id") or result.get("task_id")
            assistant_text = str(
                result.get("final_result") or result.get("status", "routed")
            )
        else:
            assistant_text = "Final transcript ready for Supervisor; execution disabled."

        should_speak = execute and action == "forward" and bool(assistant_text.strip())
        with self._lock:
            self.conversation.add(
                VoiceTurn(
                    turn_id=uuid.uuid4().hex[:12],
                    user_text=clean,
                    assistant_text=assistant_text[:4000],
                    action=action,
                    task_id=task_id,
                )
            )
            if self._turn_started_at is not None:
                self.latency["end_to_end_ms"] = round(
                    (time.perf_counter() - self._turn_started_at) * 1000, 2
                )
            self._transition(VoiceState.IDLE, "turn_completed", task_id=task_id)
            if self.settings.conversation_mode == "single":
                self.session_active = False
            elif (
                not should_speak
                and self.settings.wake_word_enabled
                and self.session_active
            ):
                try:
                    self._start_wake_listener()
                except RuntimeError as exc:
                    return self._device_failure(str(exc))
            completed = self.status()
        if should_speak:
            spoken = self.speak(assistant_text)
            if spoken.state == VoiceState.ERROR:
                with self._lock:
                    self.store.event(
                        "tts_failed",
                        {"state": "idle", "error_code": spoken.error_code},
                    )
                    self.mic_state = MicState.OFF
                    self._transition(VoiceState.IDLE, "turn_completed_without_tts")
                    return self.status()
            return spoken
        self._arm_conversation_timeout()
        return completed

    def speak(self, text: str) -> VoiceStatus:
        with self._lock:
            if not self.settings.voice_enabled:
                return self._fail("VOICE_DISABLED", "Voice is disabled in Settings.")
            try:
                self.wake_listener.stop()
                self.mic_state = MicState.MUTED
                self._transition(VoiceState.SPEAKING, "tts_started")
                tts_started = time.perf_counter()
                self.synthesizer.speak(
                    text[:4000], self.settings.tts_voice, self.settings.tts_rate
                )
                self.latency["tts_first_audio_ms"] = round(
                    (time.perf_counter() - tts_started) * 1000, 2
                )
                threading.Thread(
                    target=self._finish_speaking,
                    name="jarvis-tts-completion",
                    daemon=True,
                ).start()
            except RuntimeError as exc:
                return self._fail(str(exc), "Text-to-speech is unavailable.")
            return self.status()

    def _finish_speaking(self) -> None:
        finished = self.synthesizer.wait_until_done(60_000)
        with self._lock:
            if self.state != VoiceState.SPEAKING:
                return
            self.mic_state = MicState.OFF
            self._transition(
                VoiceState.IDLE,
                "tts_completed" if finished else "tts_completion_timeout",
            )
            if self.settings.wake_word_enabled and self.session_active:
                try:
                    self._start_wake_listener()
                except RuntimeError as exc:
                    self._device_failure(str(exc))
                    return
            self._arm_conversation_timeout()

    def pause(self) -> VoiceStatus:
        with self._lock:
            if self.capture.active:
                self.capture.stop()
                self.capture.clear()
            self.synthesizer.stop()
            self.wake_listener.stop()
            self._wake_monitor_stop.set()
            self._partial_stop.set()
            self._cancel_conversation_timeout()
            self.mic_state = MicState.MUTED
            self._transition(VoiceState.PAUSED, "paused")
            return self.status()

    def resume(self) -> VoiceStatus:
        with self._lock:
            if self.settings.wake_word_enabled and self.session_active:
                try:
                    self._start_wake_listener()
                except RuntimeError as exc:
                    return self._device_failure(str(exc))
                return self.status()
            self.mic_state = MicState.OFF
            self._transition(VoiceState.IDLE, "resumed")
            return self.status()

    def stop(self) -> VoiceStatus:
        with self._lock:
            if self.capture.active:
                self.capture.stop()
            self.capture.clear()
            self.wake_listener.stop()
            self._wake_monitor_stop.set()
            self._partial_stop.set()
            self._cancel_conversation_timeout()
            self.synthesizer.stop()
            self.session_active = False
            self.mic_state = MicState.OFF
            self.partial_transcript = ""
            self._transition(VoiceState.IDLE, "stopped")
            return self.status()

    def _start_wake_listener(self) -> None:
        device = self.devices.validate_input(self.settings.input_device_id)
        self.mic_state = MicState.ACTIVE
        self._transition(VoiceState.WAKE_LISTENING, "wake_listening")
        self.wake_listener.start(
            device.id,
            self.wake,
            self._wake_detected,
            self._wake_failed,
            lambda: self.state == VoiceState.SPEAKING,
        )

    def _wake_detected(self) -> None:
        with self._lock:
            if not self.session_active or self.state != VoiceState.WAKE_LISTENING:
                return
            try:
                device = self.devices.validate_input(self.settings.input_device_id)
                self.capture.start(device.id, min(8, self.settings.max_record_seconds))
            except RuntimeError as exc:
                self._device_failure(str(exc))
                return
            self.mic_state = MicState.LISTENING
            self._turn_started_at = time.perf_counter()
            self.latency["wake_ms"] = 0.0
            self._transition(VoiceState.LISTENING, "wake_detected", wake_attempts=1)
            self._start_partial_transcription()
            self._wake_monitor_stop.clear()
            monitor = threading.Thread(
                target=self._monitor_wake_utterance,
                name="jarvis-vad-endpoint",
                daemon=True,
            )
            monitor.start()

    def _monitor_wake_utterance(self) -> None:
        started = time.perf_counter()
        speech_seen = False
        silent_windows = 0
        while not self._wake_monitor_stop.wait(0.2):
            if not self.capture.active or self.state != VoiceState.LISTENING:
                return
            speech = self.vad.contains_speech(self.capture.latest_pcm())
            speech_seen = speech_seen or speech
            silent_windows = 0 if speech else silent_windows + 1
            elapsed = time.perf_counter() - started
            if (speech_seen and silent_windows >= 4) or elapsed >= 8:
                self.latency["speech_end_ms"] = round(silent_windows * 200.0, 2)
                self.ptt_stop(execute=True)
                return

    def _start_partial_transcription(self) -> None:
        """Publish repeated-window ASR previews; previews never enter governance."""
        self._partial_stop.set()
        previous = self._partial_worker
        if previous is not None and previous.is_alive():
            previous.join(timeout=0.05)
        self._partial_stop.clear()
        self._partial_worker = threading.Thread(
            target=self._stream_partial_transcripts,
            name="jarvis-asr-preview",
            daemon=True,
        )
        self._partial_worker.start()

    def _stream_partial_transcripts(self) -> None:
        while not self._partial_stop.wait(0.8):
            if not self.capture.active or self.state != VoiceState.LISTENING:
                return
            pcm16 = self.capture.latest_pcm()
            if len(pcm16) < 16_000 or not self.vad.contains_speech(pcm16):
                continue
            try:
                segment = self.recognizer.transcribe(pcm16, self.settings.language)
            except RuntimeError:
                continue
            if segment.text.strip():
                self.update_partial(segment.text)

    def _wake_failed(self, code: str) -> None:
        self._fail(code, "Wake-word runtime stopped safely.")

    def _cancel_conversation_timeout(self) -> None:
        timer, self._conversation_timer = self._conversation_timer, None
        if timer is not None:
            timer.cancel()

    def _arm_conversation_timeout(self) -> None:
        with self._lock:
            self._cancel_conversation_timeout()
            if (
                not self.session_active
                or self.settings.conversation_mode != "conversation"
            ):
                return
            timer = threading.Timer(
                self.settings.conversation_timeout_seconds,
                self._conversation_timed_out,
            )
            timer.daemon = True
            self._conversation_timer = timer
            timer.start()

    def _conversation_timed_out(self) -> None:
        with self._lock:
            self._conversation_timer = None
            if self.state not in {VoiceState.IDLE, VoiceState.WAKE_LISTENING}:
                return
            self.wake_listener.stop()
            self.session_active = False
            self.mic_state = MicState.OFF
            self._transition(VoiceState.IDLE, "conversation_timeout")

    def status(self) -> VoiceStatus:
        input_name = output_name = None
        try:
            input_name = self.devices.validate_input(self.settings.input_device_id).name
            output = self.devices.validate_output(self.settings.output_device_id)
            output_name = output.name if output else None
        except RuntimeError:
            pass
        return VoiceStatus(
            state=self.state,
            mic_state=self.mic_state,
            session_active=self.session_active,
            partial_transcript=self.partial_transcript,
            final_transcript=self.final_transcript,
            error_code=self.error_code,
            error_message=self.error_message,
            input_device=input_name,
            output_device=output_name,
            asr_status="AVAILABLE" if self.recognizer.available() else "NOT_CONFIGURED",
            wake_status=("AVAILABLE" if self.wake.available() else "NOT_CONFIGURED")
            if self.settings.wake_word_enabled
            else "DISABLED",
            tts_status="AVAILABLE" if self.synthesizer.available() else "UNAVAILABLE",
            settings=self.settings,
            latency=self.latency,
            turns=self.conversation.turns(),
        )

    def _transition(self, state: VoiceState, event: str, **metadata: Any) -> None:
        self.state = state
        self.error_code = self.error_message = None
        self.store.event(event, {"state": state.value, **metadata})

    def _fail(self, code: str, message: str) -> VoiceStatus:
        with self._lock:
            self.state = VoiceState.ERROR
            self.mic_state = (
                MicState.ERROR if "MIC" in code or "AUDIO" in code else MicState.OFF
            )
            self.error_code = code
            self.error_message = message
            self.store.event("voice_error", {"state": "error", "error_code": code})
            return self.status()

    def _device_failure(self, code: str) -> VoiceStatus:
        with self._lock:
            self.state = VoiceState.PAUSED
            self.mic_state = MicState.ERROR
            self.error_code = "DEVICE_UNAVAILABLE"
            self.error_message = "The selected microphone was disconnected. Voice is paused."
            self.store.event(
                "voice_device_unavailable",
                {"state": "paused", "error_code": code},
            )
            return self.status()
