# M6-A Architecture — Multi-Provider Expert Team and JARVIS Voice

## Governed model routing

```text
Agent role slot
  -> RoleModelRouter (task > project > global > explicit fallback)
  -> MultiProviderRoutedProvider
  -> existing ModelGateway (single budget/audit ledger)
  -> provider-specific adapter
  -> real provider
```

The business layer selects stable slots, never provider names. Each provider credential is resolved
from its own `SecretStore` key only at adapter construction. Unknown capabilities remain unknown.
Fallback is absent unless a complete provider/model pair is saved by the user. Reviewer remains a
read-only role; using the Executor model for Reviewer is allowed only with a visible warning.

Performance profiles record calls, structured-output success, coding/review/tool outcomes, errors,
latency, tokens, and cost. They are observational and never rewrite routing. Per-role token limits
are applied to each request. A configured per-role cost limit fails closed when cost cannot be
verified.

## Local-first voice path

```text
sounddevice / WASAPI
  -> bounded 16 kHz mono memory queue
  -> SileroOnnxVADAdapter
  -> openWakeWord (optional, default OFF) or push-to-talk
  -> WhisperCppAdapter
  -> final transcript only
  -> local safety intent
  -> configured Supervisor slot
  -> AI Team / WindowsActionGateway / DesktopObserver
  -> UI text immediately
  -> asynchronous Windows SAPI TTS
```

Partial transcript state is UI-only. Raw microphone frames and wake circular buffers never enter
Memory, Evidence, artifacts, checkpoints, audit payloads, Git, or the source package. whisper.cpp's
short-lived scratch WAV is created under the current-user temporary directory and deleted in a
`finally` block before the adapter returns.

`STOP`, `Cancel`, `Pause`, and `Reject` are exact local deterministic intents. Longer sentences are
not substring-matched. Voice approval is denied; medium/high-risk approval remains a visible UI
action. STOP also invokes the existing Computer Control emergency stop.

The voice state machine is:

```text
idle -> wake_listening/listening -> transcribing -> thinking -> speaking
                  |                    |              |
                  +-> paused/error     +-> error      +-> interrupted/listening
```

Wake listening uses a bounded local queue. After activation, VAD detects speech and four
consecutive 200 ms silent windows end the utterance; an eight-second ceiling prevents unbounded
capture. Push-to-talk remains available without wake models.

Conversation context is process-memory working context only. It is bounded by both recent turns and
an approximate token ceiling, and only a small recent summary is supplied to the next Supervisor
turn. It does not become long-term Memory without the existing MemoryProposal policy.
