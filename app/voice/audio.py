from __future__ import annotations

import queue
import threading
from collections import deque
from typing import Any

from app.voice.adapters import WakeWordDetector


class AudioCaptureService:
    """Bounded 16 kHz mono in-memory capture; buffers are erased on every stop."""

    sample_rate = 16_000
    channels = 1

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend
        self._stream: Any | None = None
        self._chunks: queue.Queue[bytes] = queue.Queue()
        self._lock = threading.Lock()
        self._max_bytes = self.sample_rate * 2 * 30
        self._captured_bytes = 0
        self._recent: deque[bytes] = deque(maxlen=10)
        self._recent_lock = threading.Lock()

    def _sounddevice(self) -> Any:
        if self._backend is not None:
            return self._backend
        try:
            import sounddevice  # type: ignore[import-not-found,import-untyped]
        except ImportError as exc:
            raise RuntimeError("AUDIO_RUNTIME_UNAVAILABLE") from exc
        return sounddevice

    def start(self, device_id: int | None, max_seconds: int) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self.clear()
            self._max_bytes = self.sample_rate * 2 * max_seconds

            def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
                del frames, time_info, status
                data = bytes(indata)
                if self._captured_bytes + len(data) > self._max_bytes:
                    return
                self._chunks.put_nowait(data)
                with self._recent_lock:
                    self._recent.append(data)
                self._captured_bytes += len(data)

            backend = self._sounddevice()
            self._stream = backend.RawInputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                device=device_id,
                blocksize=1600,
                callback=callback,
            )
            self._stream.start()

    def stop(self) -> bytes:
        with self._lock:
            stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        chunks: list[bytes] = []
        while True:
            try:
                chunks.append(self._chunks.get_nowait())
            except queue.Empty:
                break
        audio = b"".join(chunks)
        self._captured_bytes = 0
        with self._recent_lock:
            self._recent.clear()
        return audio

    def clear(self) -> None:
        while True:
            try:
                self._chunks.get_nowait()
            except queue.Empty:
                break
        self._captured_bytes = 0
        with self._recent_lock:
            self._recent.clear()

    @property
    def active(self) -> bool:
        return self._stream is not None

    def latest_pcm(self) -> bytes:
        with self._recent_lock:
            return b"".join(self._recent)


class WakeWordListener:
    """Bounded local wake loop; only a few frames are retained in memory."""

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend
        self._stream: Any | None = None
        self._frames: queue.Queue[bytes] = queue.Queue(maxsize=12)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def _sounddevice(self) -> Any:
        if self._backend is not None:
            return self._backend
        try:
            import sounddevice  # type: ignore[import-not-found,import-untyped]
        except ImportError as exc:
            raise RuntimeError("AUDIO_RUNTIME_UNAVAILABLE") from exc
        return sounddevice

    def start(
        self,
        device_id: int,
        detector: WakeWordDetector,
        on_detected: Any,
        on_error: Any,
        output_suppressed: Any,
    ) -> None:
        if self.active:
            return
        self._stop.clear()

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            del frames, time_info, status
            try:
                self._frames.put_nowait(bytes(indata))
            except queue.Full:
                try:
                    self._frames.get_nowait()
                    self._frames.put_nowait(bytes(indata))
                except queue.Empty:
                    pass

        backend = self._sounddevice()
        self._stream = backend.RawInputStream(
            samplerate=16_000,
            channels=1,
            dtype="int16",
            device=device_id,
            blocksize=1280,
            callback=callback,
        )
        self._stream.start()

        def run() -> None:
            try:
                while not self._stop.is_set():
                    try:
                        frame = self._frames.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if output_suppressed():
                        continue
                    if detector.score(frame) >= detector.threshold:
                        self._stop.set()
                        self._close_stream()
                        on_detected()
                        return
            except RuntimeError as exc:
                self._stop.set()
                self._close_stream()
                on_error(str(exc))
            finally:
                self.clear()

        self._worker = threading.Thread(target=run, name="jarvis-wake-listener", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_stream()
        worker, self._worker = self._worker, None
        if worker and worker is not threading.current_thread():
            worker.join(timeout=1)
        self.clear()

    def clear(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                break

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()

    @property
    def active(self) -> bool:
        return self._stream is not None
