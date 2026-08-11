from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from app.voice.adapters import SileroOnnxVadAdapter
from app.voice.models import AudioDevice, TranscriptSegment, VoiceSettings, VoiceState
from app.voice.service import VoiceService


class FakeDevices:
    disconnected = False

    def list_devices(self):
        return [
            AudioDevice(
                id=3,
                name="Test microphone",
                input_channels=1,
                output_channels=0,
                default_sample_rate=48_000,
                is_default_input=True,
            ),
            AudioDevice(
                id=4,
                name="Test speaker",
                input_channels=0,
                output_channels=2,
                default_sample_rate=48_000,
                is_default_output=True,
            ),
        ]

    def validate_input(self, device_id):
        if self.disconnected:
            raise RuntimeError("INPUT_DEVICE_DISCONNECTED")
        return self.list_devices()[0]

    def validate_output(self, device_id):
        return self.list_devices()[1]


class FakeCapture:
    def __init__(self) -> None:
        self.active = False
        self.cleared = 0
        self.preview = b""

    def start(self, device_id, max_seconds):
        assert device_id == 3
        assert max_seconds <= 120
        self.active = True

    def stop(self):
        self.active = False
        return b"\x00\x10" * 16_000

    def clear(self):
        self.cleared += 1

    def latest_pcm(self):
        return self.preview


class FakeRecognizer:
    def __init__(self, text: str = "检查当前窗口") -> None:
        self.text = text
        self.calls = 0
        self.failure = ""

    def available(self):
        return True

    def transcribe(self, pcm16, language="auto"):
        self.calls += 1
        if self.failure:
            raise RuntimeError(self.failure)
        assert pcm16
        return TranscriptSegment(text=self.text, ended_ms=1000, language=language)


class FakeSynthesizer:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.stops = 0

    def available(self):
        return True

    def speak(self, text, voice="", rate=0):
        self.spoken.append(text)

    def stop(self):
        self.stops += 1

    def wait_until_done(self, timeout_ms):
        assert timeout_ms <= 60_000
        time.sleep(0.05)
        return True


def make_service(tmp_path: Path, *, turns: int = 12):
    devices = FakeDevices()
    capture = FakeCapture()
    recognizer = FakeRecognizer()
    synth = FakeSynthesizer()
    supervisor_calls: list[str] = []
    local_calls: list[str] = []

    def supervisor(text: str):
        supervisor_calls.append(text)
        return {"status": "completed", "run_id": "voice-run"}

    def local(action: str):
        local_calls.append(action)
        return {"status": action}

    service = VoiceService(
        tmp_path,
        devices=devices,
        capture=capture,
        recognizer=recognizer,
        synthesizer=synth,
        supervisor=supervisor,
        local_action=local,
    )
    service.update_settings(
        VoiceSettings(
            voice_enabled=True,
            microphone_enabled=True,
            max_session_turns=turns,
        )
    )
    return service, devices, capture, recognizer, synth, supervisor_calls, local_calls


def test_gt_voice01_defaults_are_off(tmp_path: Path):
    service = VoiceService(tmp_path, devices=FakeDevices(), synthesizer=FakeSynthesizer())
    status = service.status()
    assert status.settings.voice_enabled is False
    assert status.settings.microphone_enabled is False
    assert status.mic_state == "MIC OFF"


def test_gt_voice02_devices_are_visible_without_audio_data(tmp_path: Path):
    service, devices, *_ = make_service(tmp_path)
    assert [item.name for item in devices.list_devices()] == [
        "Test microphone",
        "Test speaker",
    ]
    assert service.status().raw_audio_persisted is False


def test_gt_voice03_session_without_wake_stays_idle(tmp_path: Path):
    service, *_ = make_service(tmp_path)
    status = service.start_session()
    assert status.session_active is True
    assert status.state == VoiceState.IDLE
    assert status.wake_status == "DISABLED"


def test_gt_voice04_ptt_final_routes_only_once_to_supervisor(tmp_path: Path):
    service, _, capture, recognizer, _, supervisor, _ = make_service(tmp_path)
    assert service.ptt_start().state == VoiceState.LISTENING
    status = service.ptt_stop()
    assert recognizer.calls == 1
    assert supervisor == ["检查当前窗口"]
    assert capture.cleared >= 1
    assert status.turns[-1].route == "supervisor"
    assert status.turns[-1].task_id == "voice-run"


def test_gt_voice05_partial_transcript_never_executes(tmp_path: Path):
    service, _, _, _, _, supervisor, local = make_service(tmp_path)
    service.ptt_start()
    status = service.update_partial("停止")
    assert status.partial_transcript == "停止"
    assert supervisor == []
    assert local == []


def test_streaming_preview_is_local_and_never_executes(tmp_path: Path) -> None:
    service, _, capture, recognizer, _, supervisor, local = make_service(tmp_path)
    service.ptt_start()
    capture.preview = b"\x00\x10" * 16_000
    deadline = time.monotonic() + 2.0
    while not service.status().partial_transcript and time.monotonic() < deadline:
        time.sleep(0.05)
    assert service.status().partial_transcript == recognizer.text
    assert recognizer.calls >= 1
    assert supervisor == local == []
    service.ptt_stop(execute=False)


def test_gt_voice06_stop_is_local_before_model(tmp_path: Path):
    service, *_, supervisor, local = make_service(tmp_path)
    status = service.submit_final("立即停止")
    assert local == ["stop"]
    assert supervisor == []
    assert status.turns[-1].action == "stop"


def test_gt_voice07_cancel_is_local_before_model(tmp_path: Path):
    service, *_, supervisor, local = make_service(tmp_path)
    service.submit_final("取消操作")
    assert local == ["cancel"]
    assert supervisor == []


def test_gt_voice08_pause_is_local_before_model(tmp_path: Path):
    service, *_, supervisor, local = make_service(tmp_path)
    service.submit_final("暂停")
    assert local == ["pause"]
    assert supervisor == []


def test_gt_voice09_reject_is_local_before_model(tmp_path: Path):
    service, *_, supervisor, local = make_service(tmp_path)
    service.submit_final("拒绝操作")
    assert local == ["reject"]
    assert supervisor == []


def test_gt_voice10_voice_cannot_approve(tmp_path: Path):
    service, *_, supervisor, local = make_service(tmp_path)
    status = service.submit_final("批准")
    assert local == []
    assert supervisor == []
    assert status.turns[-1].action == "approval_denied_by_voice"
    assert "visible approval" in status.turns[-1].assistant_text


def test_gt_voice11_longer_negated_phrase_is_not_misclassified(tmp_path: Path):
    service, *_, supervisor, local = make_service(tmp_path)
    service.submit_final("不要点击删除按钮，先告诉我风险")
    assert local == []
    assert supervisor == ["不要点击删除按钮，先告诉我风险"]


def test_gt_voice12_db_contains_no_transcript_or_audio(tmp_path: Path):
    service, *_ = make_service(tmp_path)
    secret_phrase = "这段语音绝不能写入数据库"
    service.submit_final(secret_phrase, execute=False)
    db = tmp_path / "runtime" / "voice" / "voice.sqlite"
    with sqlite3.connect(db) as conn:
        events = " ".join(row[0] for row in conn.execute("SELECT metadata FROM voice_events"))
        schema = " ".join(row[0] for row in conn.execute("SELECT sql FROM sqlite_master"))
    assert secret_phrase not in events
    assert "audio" not in schema.lower()


def test_gt_voice13_asr_failure_executes_nothing_and_clears_buffer(tmp_path: Path):
    service, _, capture, recognizer, _, supervisor, local = make_service(tmp_path)
    recognizer.failure = "ASR_INFERENCE_FAILED"
    service.ptt_start()
    status = service.ptt_stop()
    assert status.state == VoiceState.ERROR
    assert status.error_code == "TRANSCRIPTION_FAILED"
    assert capture.cleared >= 1
    assert supervisor == local == []


def test_gt_voice14_ptt_barge_in_stops_tts(tmp_path: Path):
    service, _, _, _, synth, *_ = make_service(tmp_path)
    service.start_session()
    assert service.speak("正在播报").state == VoiceState.SPEAKING
    assert service.ptt_start().state == VoiceState.LISTENING
    assert synth.stops >= 1


def test_gt_voice15_conversation_is_bounded(tmp_path: Path):
    service, *_ = make_service(tmp_path, turns=2)
    service.submit_final("第一条", execute=False)
    service.submit_final("第二条", execute=False)
    status = service.submit_final("第三条", execute=False)
    assert [turn.user_text for turn in status.turns] == ["第二条", "第三条"]


def test_gt_voice16_hotplug_failure_is_safe(tmp_path: Path):
    service, devices, _, _, _, supervisor, local = make_service(tmp_path)
    devices.disconnected = True
    status = service.ptt_start()
    assert status.state == VoiceState.PAUSED
    assert status.error_code == "DEVICE_UNAVAILABLE"
    assert supervisor == local == []


def test_conversation_timeout_returns_to_idle(tmp_path: Path) -> None:
    service, *_ = make_service(tmp_path)
    service.settings.conversation_timeout_seconds = 0
    service.start_session()
    service.submit_final("preview only", execute=False)
    deadline = time.monotonic() + 1.0
    while service.status().session_active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.status().state == VoiceState.IDLE
    assert service.status().session_active is False


def test_vad_rejects_silence_and_accepts_voice_energy() -> None:
    vad = SileroOnnxVadAdapter()
    assert vad.contains_speech(bytes(32_000)) is False
    assert vad.contains_speech(b"\x00\x10" * 16_000) is True


def test_supervisor_failure_is_safe_and_has_no_provider_details(tmp_path: Path) -> None:
    service, *_ = make_service(tmp_path)

    def fail(_text: str):
        raise RuntimeError("SECRET-UPSTREAM-TRACE")

    service.supervisor = fail
    status = service.submit_final("检查页面")
    assert status.state == VoiceState.ERROR
    assert status.error_code == "SUPERVISOR_FAILED"
    assert "SECRET-UPSTREAM-TRACE" not in (status.error_message or "")


def test_missing_supervisor_route_has_explicit_waiting_status(tmp_path: Path) -> None:
    service, *_ = make_service(tmp_path)

    class WaitingError(RuntimeError):
        safe_message = "WAITING_FOR_PROVIDER_CREDENTIAL"

    def wait(_text: str):
        raise WaitingError("SECRET-PROVIDER-DETAIL")

    service.supervisor = wait
    status = service.submit_final("check the current page")
    assert status.state == VoiceState.ERROR
    assert status.error_code == "WAITING_FOR_PROVIDER_CREDENTIAL"
    assert "SECRET-PROVIDER-DETAIL" not in (status.error_message or "")
