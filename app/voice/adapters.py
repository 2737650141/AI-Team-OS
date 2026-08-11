from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import wave
from array import array
from pathlib import Path
from typing import Any, Protocol

from app.voice.models import TranscriptSegment


class SpeechRecognizer(Protocol):
    def available(self) -> bool: ...
    def transcribe(self, pcm16: bytes, language: str = "auto") -> TranscriptSegment: ...


class SpeechSynthesizer(Protocol):
    def available(self) -> bool: ...
    def speak(self, text: str, voice: str = "", rate: int = 0) -> None: ...
    def stop(self) -> None: ...
    def wait_until_done(self, timeout_ms: int) -> bool: ...


class VoiceActivityDetector(Protocol):
    def available(self) -> bool: ...
    def contains_speech(self, pcm16: bytes) -> bool: ...


class WakeWordDetector(Protocol):
    threshold: float
    def available(self) -> bool: ...
    def score(self, pcm16: bytes) -> float: ...


class WhisperCppAdapter:
    """whisper.cpp CLI adapter. Its ephemeral WAV is deleted before returning."""

    def __init__(self, executable: str = "", model: str = "", timeout_seconds: int = 45) -> None:
        self.executable = Path(executable) if executable else None
        self.model = Path(model) if model else None
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        return bool(
            self.executable
            and self.model
            and self.executable.is_file()
            and self.model.is_file()
        )

    def transcribe(self, pcm16: bytes, language: str = "auto") -> TranscriptSegment:
        if not self.available():
            raise RuntimeError("ASR_NOT_CONFIGURED")
        if not pcm16:
            raise RuntimeError("EMPTY_AUDIO")
        path = ""
        try:
            with tempfile.NamedTemporaryFile(
                prefix="aitos-voice-", suffix=".wav", delete=False
            ) as tmp:
                path = tmp.name
            with wave.open(path, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16_000)
                output.writeframes(pcm16)
            command = [
                str(self.executable),
                "-m",
                str(self.model),
                "-f",
                path,
                "-nt",
                "-t",
                "4",
            ]
            if language in {"zh", "en"}:
                command.extend(["-l", language])
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                raise RuntimeError("ASR_INFERENCE_FAILED")
            duration_ms = int(len(pcm16) / 2 / 16_000 * 1000)
            return TranscriptSegment(
                text=result.stdout.strip(),
                ended_ms=duration_ms,
                language=language if language != "auto" else "unknown",
            )
        finally:
            if path:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass


class SileroOnnxVadAdapter:
    """Silero integration point plus conservative local silence pre-check."""

    def __init__(self, model_path: str = "") -> None:
        self.model_path = Path(model_path) if model_path else None
        self._session: Any | None = None

    def available(self) -> bool:
        return bool(self.model_path and self.model_path.is_file())

    def contains_speech(self, pcm16: bytes) -> bool:
        if len(pcm16) < 320:
            return False
        if self.available():
            try:
                return self._silero_probability(pcm16) >= 0.5
            except (ImportError, RuntimeError, ValueError):
                # Safe local degradation: silence gating remains available when the
                # optional ONNX runtime/model is incompatible, but never invokes cloud ASR.
                pass
        samples = array("h")
        samples.frombytes(pcm16)
        mean_square = sum(value * value for value in samples) / max(1, len(samples))
        return mean_square**0.5 >= 120

    def _silero_probability(self, pcm16: bytes) -> float:
        import numpy as np
        import onnxruntime as ort  # type: ignore[import-not-found,import-untyped]

        if self._session is None:
            self._session = ort.InferenceSession(
                str(self.model_path), providers=["CPUExecutionProvider"]
            )
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        input_names = {item.name for item in self._session.get_inputs()}
        state = np.zeros((2, 1, 128), dtype=np.float32)
        hidden = np.zeros((2, 1, 64), dtype=np.float32)
        cell = np.zeros((2, 1, 64), dtype=np.float32)
        maximum = 0.0
        for offset in range(0, len(audio), 512):
            chunk = audio[offset : offset + 512]
            if len(chunk) < 512:
                chunk = np.pad(chunk, (0, 512 - len(chunk)))
            feed = {
                "input": chunk.reshape(1, -1),
                "sr": np.array(16_000, dtype=np.int64),
            }
            if {"h", "c"}.issubset(input_names):
                output, hidden, cell = self._session.run(
                    None, {**feed, "h": hidden, "c": cell}
                )
            else:
                output, state = self._session.run(None, {**feed, "state": state})
            maximum = max(maximum, float(np.asarray(output).reshape(-1)[0]))
        return maximum


class OpenWakeWordAdapter:
    def __init__(self, model_path: str = "", threshold: float = 0.65) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.threshold = threshold
        self._model: Any | None = None

    def available(self) -> bool:
        return bool(self.model_path and self.model_path.is_file())

    def score(self, pcm16: bytes) -> float:
        if not self.available():
            raise RuntimeError("WAKE_MODEL_NOT_CONFIGURED")
        if self._model is None:
            try:
                from openwakeword.model import Model  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError("WAKE_RUNTIME_UNAVAILABLE") from exc
            self._model = Model(
                wakeword_models=[str(self.model_path)], inference_framework="onnx"
            )
        import numpy as np

        predictions = self._model.predict(np.frombuffer(pcm16, dtype=np.int16))
        return max((float(value) for value in predictions.values()), default=0.0)


class WindowsSapiSynthesizer:
    """Asynchronous local SAPI TTS; purge implements interruption/barge-in."""

    def __init__(self) -> None:
        self._voice: Any | None = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return os.name == "nt"

    def _sapi(self) -> Any:
        if self._voice is None:
            try:
                import win32com.client  # type: ignore[import-not-found,import-untyped]
            except ImportError as exc:
                raise RuntimeError("TTS_RUNTIME_UNAVAILABLE") from exc
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
        return self._voice

    def speak(self, text: str, voice: str = "", rate: int = 0) -> None:
        if not text.strip():
            return
        with self._lock:
            sapi = self._sapi()
            sapi.Rate = rate
            if voice:
                for token in sapi.GetVoices():
                    if voice.lower() in token.GetDescription().lower():
                        sapi.Voice = token
                        break
            sapi.Speak(text, 3)  # async + purge prior output

    def stop(self) -> None:
        with self._lock:
            if self._voice is not None:
                self._voice.Speak("", 3)

    def wait_until_done(self, timeout_ms: int) -> bool:
        voice = self._voice
        if voice is None:
            return True
        initialized = False
        try:
            import pythoncom  # type: ignore[import-not-found,import-untyped]

            pythoncom.CoInitialize()
            initialized = True
            return bool(voice.WaitUntilDone(timeout_ms))
        except Exception:
            return False
        finally:
            if initialized:
                pythoncom.CoUninitialize()
