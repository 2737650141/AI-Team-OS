from __future__ import annotations

from typing import Any

from app.voice.models import AudioDevice


class AudioDeviceManager:
    """Small adapter around PortAudio/sounddevice with safe hot-plug refresh."""

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend

    def _sounddevice(self) -> Any:
        if self._backend is not None:
            return self._backend
        try:
            import sounddevice  # type: ignore[import-not-found,import-untyped]
        except ImportError as exc:
            raise RuntimeError("AUDIO_RUNTIME_UNAVAILABLE") from exc
        return sounddevice

    def list_devices(self) -> list[AudioDevice]:
        backend = self._sounddevice()
        try:
            default_input, default_output = backend.default.device
        except (TypeError, ValueError):
            default_input, default_output = -1, -1
        devices: list[AudioDevice] = []
        for index, item in enumerate(backend.query_devices()):
            devices.append(
                AudioDevice(
                    id=index,
                    name=str(item.get("name", f"Audio device {index}")),
                    input_channels=int(item.get("max_input_channels", 0)),
                    output_channels=int(item.get("max_output_channels", 0)),
                    default_sample_rate=float(item.get("default_samplerate", 0)),
                    is_default_input=index == default_input,
                    is_default_output=index == default_output,
                )
            )
        return devices

    def validate_input(self, device_id: int | None) -> AudioDevice:
        inputs = [item for item in self.list_devices() if item.input_channels > 0]
        if not inputs:
            raise RuntimeError("NO_INPUT_DEVICE")
        if device_id is None:
            return next((item for item in inputs if item.is_default_input), inputs[0])
        device = next((item for item in inputs if item.id == device_id), None)
        if device is None:
            raise RuntimeError("INPUT_DEVICE_DISCONNECTED")
        return device

    def validate_output(self, device_id: int | None) -> AudioDevice | None:
        outputs = [item for item in self.list_devices() if item.output_channels > 0]
        if not outputs:
            return None
        if device_id is None:
            return next((item for item in outputs if item.is_default_output), outputs[0])
        return next((item for item in outputs if item.id == device_id), None)
