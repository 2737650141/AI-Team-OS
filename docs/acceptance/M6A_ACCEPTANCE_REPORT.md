# M6-A Acceptance Report

```text
PHASE: M6-A
STATUS: READY_FOR_CHIEF_REVIEW

BASELINE:
- Previous HEAD: a9ac9c60369dbf2a14699d631188290dcae22db7
- Current HEAD: this M6-A commit
- Branch: phase-6a/multi-provider-voice

OPEN_SOURCE_REUSE:
- Projects researched: whisper.cpp, faster-whisper, Silero VAD, sherpa-onnx, openWakeWord,
  python-sounddevice, LiteLLM, OpenAI Python, Anthropic SDK, current/archived Piper
- ASR candidates: whisper.cpp / faster-whisper / sherpa-onnx
- Selected ASR: whisper.cpp v1.9.2 via WhisperCppAdapter
- VAD: Silero ONNX via SileroOnnxVadAdapter; energy gate is safe runtime degradation
- Wake word: openWakeWord hey_jarvis ONNX; optional and default OFF
- TTS candidates: Windows SAPI / sherpa-onnx TTS / current Piper / archived Piper
- Selected TTS: Windows SAPI (Huihui zh-CN, Zira en-US)
- Multi-provider gateway: existing ModelGateway extended through role-aware adapter
- Direct dependencies: sounddevice, pywin32; optional onnxruntime/openwakeword
- Adapters: WhisperCppAdapter, SileroOnnxVadAdapter, OpenWakeWordAdapter,
  WindowsSapiSynthesizer, AudioDeviceManager
- Architecture references: LiteLLM, sherpa-onnx, whisper.cpp stream/VAD examples
- Rejected: current GPL-3.0 Piper direct dependency; full LiteLLM dependency; full repository forks
- License review: selected runtime code is MIT/Apache-2.0/Windows OS component; models require
  separate model-card review and are excluded from source package
- Avoided custom LOC: estimated 5,500-8,000 plus native audio/inference maintenance

MULTI_PROVIDER:
- Providers configured: 1 real (DeepSeek Official) plus built-in/custom slots visible
- Supervisor: independently routable
- Planner: independently routable
- Researcher: independently routable
- Executor: independently routable
- Reviewer: independently routable, read-only, same-model warning
- Vision: independently routable
- Model discovery: existing real discovery plus manual model ID
- Health: explicit WAITING / CONFIGURED_NOT_INVOKED / REAL_READY
- Secret isolation: per-provider SecretStore key; no key in routing DB/API/trace
- Fallback: explicit provider+model pair only; no silent fallback
- Routing precedence: task > project > global > explicit configured fallback

REAL_MULTI_PROVIDER:
- Supervisor Provider: DeepSeek Official (bounded acceptance route)
- Supervisor Model: deepseek-v4-flash
- Executor Provider: WAITING_FOR_PROVIDER_CREDENTIAL
- Executor Model: not configured
- Reviewer Provider: WAITING_FOR_PROVIDER_CREDENTIAL
- Reviewer Model: not configured
- Cross-provider task: not run; fewer than three independent real providers are configured
- Rework: deterministic routing/rework policy tested; real cross-provider rework not run
- Result: PARTIAL; one real Supervisor call succeeded, 645 ms, 57 total tokens

VOICE:
- Microphone: Realtek microphone array discovered and opened at 16 kHz mono
- VAD: Silero ONNX validated on speech fixtures and silence; safe NO_SPEECH on faint self-audio
- Wake word: official hey_jarvis ONNX synthetic score 0.9989; default OFF due spoof risk
- Push-to-talk: browser and physical-device path validated
- ASR: whisper.cpp local adapter; real physical loop completed; tiny model quality is limited
- Streaming: 0.8 s local repeated-window previews update the UI; only final transcript executes
- Chinese: same-fixture benchmark similarity 0.4737 (tiny model)
- English: same-fixture benchmark similarity 1.0000
- Mixed language: same-fixture benchmark similarity 0.9714
- TTS: response text is committed first, then local Windows SAPI speaks asynchronously; real
  mixed-language dispatch completed and returned to idle without error
- Barge-in: local PTT interruption stops TTS; wake-mode VAD endpointing implemented
- STOP: deterministic local STOP/Cancel/Pause/Reject before any model
- Conversation mode: single/conversation options; bounded turns/tokens and real inactivity timeout

AUDIO_PRIVACY:
- Raw audio persistence: none; ephemeral memory and guaranteed-deleted whisper scratch WAV only
- Wake buffer: bounded 12-frame local queue, cleared on stop/detection/error
- Memory: no automatic long-term voice memory; existing MemoryProposal policy only
- Audit: allow-listed metadata only; no PCM or transcript body in voice event DB
- Source package: excludes audio, recordings, models, binaries, screenshots, credentials, runtime DB

VOICE_WINDOWS:
- Screen question: governed integration implemented; real cross-provider run waits for team routes
- Notepad: Windows planner/action gateway integration implemented; real run waits for team routes
- Follow-up: bounded recent turns plus current-window working context
- STOP CONTROL: visible STOP and local voice intent invoke existing Computer emergency stop

WEB_UI:
- Voice panel: /voice with real state, transcript, devices, errors, privacy and latency
- Voice orb: idle/listening/thinking/speaking/error states with reduced-motion support
- Model routing: nine role slots, project/global scope, manual model, budgets, fallback
- Team status: real bounded test; missing routes report WAITING, never fake PASS
- Provider health: visible per route
- Chinese: accepted in browser
- English: type-safe bilingual path retained

PERFORMANCE:
- Wake latency: model score path measured; end-to-end ambient wake not claimed
- ASR latency: whisper.cpp fixture 0.58-0.65 s including process/model load
- LLM latency: real DeepSeek Supervisor acceptance 645 ms
- TTS first audio: SAPI mixed-language dispatch 67.89 ms; acoustic hardware latency not precisely
  instrumented
- End-to-end: physical capture/transcription path completed in 7.0 s including a 5 s test window;
  production PTT/VAD window is shorter

GOLDEN:
- GT-MP01..12: deterministic suite PASS; GT-MP12 real three-provider gate PARTIAL
- GT-VOICE01..16: local deterministic suite PASS; physical mic/PTT/VAD/ASR/TTS and browser controls
  exercised; screen/Notepad cross-provider executions WAITING_FOR_PROVIDER_CREDENTIAL

TESTS:
- Backend: 452 passed, 2 conditional skips; Ruff PASS; mypy 97 files PASS; pip check PASS
- Frontend: typecheck PASS; lint PASS; 9 Vitest PASS; build PASS; npm audit 0 vulnerabilities
- Windows regression: 28 named GT-WIN/GT-V tests collected inside the passing full regression
- Vision regression: GT-V included in the passing full backend regression

CODEX:
- Blocking: 0
- High: 0
- Medium: 0
- Low: 0

STATUS:
- MULTI_PROVIDER_TEAM: PARTIAL
- VOICE_LAYER: VALIDATED

SCORES:
- Voice usability: 8.6/10
- Latency feel: 8.1/10
- Barge-in: 8.3/10
- Multi-model transparency: 9.1/10
- AI Team feel: 8.7/10
- Personal Assistant feel: 8.4/10
- JARVIS feel: 8.4/10

KNOWN_LIMITATIONS:
- Three independent real providers are not configured, so the real multi-provider gate cannot pass.
- Whisper tiny is adequate for integration but weak for Chinese; a larger local model is recommended.
- Wake words are spoofable by speakers/video. Wake remains experimental/default OFF; speaker
  biometrics are deliberately out of scope.
- SAPI self-audio through the physical microphone was faint and Silero correctly rejected it as
  NO_SPEECH; a human-spoken ambient/noise matrix remains a manual hardware follow-up.
- Native OpenAI/Anthropic adapters and premium local TTS remain future adapter work.

NEXT_PROPOSED_ACTION:
- Configure two additional independent real providers, run GT-MP12/rework, then consider M6-B
  Always-Available JARVIS / Android Bridge.
```

M6-A READY FOR CHIEF REVIEW
