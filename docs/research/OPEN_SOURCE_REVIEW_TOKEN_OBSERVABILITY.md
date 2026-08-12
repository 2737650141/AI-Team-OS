# Open Source Review — Token & Context Observatory (M6-P2)

Reviewed 2026-08-12. The assessment covered primary documentation, repository README and
architecture, license, recent activity/releases, issues/security surface, dependencies, core
usage structures, examples, and tests where available. No full repository is forked.

| Repository / source | Purpose | License / activity | Relevant components | Reuse level | Decision |
|---|---|---|---|---|---|
| [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) | Vendor-neutral GenAI telemetry names | Apache-2.0 specification; active | input/output usage, provider/model, duration concepts | LEVEL 4 — Architecture Reference | Shape the normalized schema while keeping local SQLite and AI Team OS privacy policy. |
| [OpenAI API usage schema](https://platform.openai.com/docs/api-reference/responses-streaming/response/output_item/added) | Authoritative OpenAI response usage | Official API docs | cached input detail and reasoning output detail | LEVEL 2 — Adapter Integration | Provider response is authoritative; cached/reasoning remain subsets, not additive totals. |
| [Anthropic usage/pricing](https://docs.anthropic.com/en/docs/about-claude/pricing) | Authoritative Messages usage semantics | Official docs | input, cache creation, cache read, output | LEVEL 2 — Adapter Integration | Inclusive normalized input is the documented sum of the three input categories. |
| [DeepSeek chat completion](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/) | Authoritative DeepSeek usage schema | Official docs; current | prompt/completion/total, prompt cache hit/miss, reasoning detail | LEVEL 2 — Adapter Integration | Implemented in the OpenAI-compatible adapter with explicit DeepSeek semantics. |
| [LiteLLM](https://github.com/BerriAI/litellm) | 100+ provider normalization, cost and gateway | MIT; ~42k commits, active | provider adapters, model price/context registry, callbacks | LEVEL 4 — Architecture Reference | Rejected as a direct dependency: it would duplicate the governed gateway, greatly expand the sidecar, and spread a large dependency surface. Model registry separation influenced the design. |
| [LangChain messages](https://docs.langchain.com/oss/javascript/langchain/messages) / [LangGraph events](https://docs.langchain.com/oss/python/langgraph/event-streaming) | Common usage metadata and execution event patterns | MIT; active | usage metadata, cache/reasoning details, event timeline | LEVEL 4 — Architecture Reference | Keep current LangGraph dependency; adapt its event pattern rather than adding LangChain runtime types to business code. |
| [tiktoken](https://github.com/openai/tiktoken) | Fast OpenAI BPE tokenizer | MIT; active, 19k stars, tested; 3–6x benchmark claim | model-aware local pre-call token estimate | LEVEL 1 — Direct Dependency | Added for OpenAI model estimates only. Unknown/non-OpenAI encodings return unavailable; provider-reported final usage wins. |
| [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) | Long-running agent continuity and automatic compaction | MIT; active, 14k stars | automatic compaction, durable harness state, rollback concepts | LEVEL 4 — Architecture Reference | Runtime rejected: different JS/Python REPL trust model and not a Windows security sandbox. Reused the separation between durable critical state and disposable conversational context. |
| [addyosmani/agent-skills context engineering](https://github.com/addyosmani/agent-skills/blob/main/skills/context-engineering/SKILL.md) | Context selection and progressive disclosure guidance | MIT repository; active | structured context, relevance, bounded loading | LEVEL 4 — Architecture Reference | Used for deterministic critical-field checkpoint design; no code copied. |
| [Tauri 2 sidecars](https://v2.tauri.app/develop/sidecar/) | Windows desktop shell and packaged Python process | Apache-2.0/MIT; active | external binary, process lifecycle | LEVEL 1 — Direct Dependency | Selected over a custom launcher. Tauri single-instance, tray, and NSIS facilities remain behind the desktop boundary. |
| [cargo-xwin](https://github.com/rust-cross/cargo-xwin) / [xwin](https://github.com/Jake-Shadle/xwin) | Portable Windows SDK/CRT acquisition for Rust linking | MIT or Apache-2.0; active | official MSVC CRT/SDK retrieval, LLVM linking | LEVEL 1 — Build Dependency | Used only when the machine lacks Visual C++ Build Tools; SDK license is explicitly accepted for build use and symlinks are disabled on non-elevated Windows. |

## Candidate comparison

| Candidate | Fit | Dependencies | Windows / Python 3.11 | Security | Integration cost | Result |
|---|---|---|---|---|---|---|
| LiteLLM | Very broad provider coverage | High; gateway/proxy stack | Supported, but large packaged footprint | Additional proxy/key/admin surface | High, duplicates existing ToolGateway/ModelGateway governance | Architecture reference only |
| OpenTelemetry GenAI | Excellent stable vocabulary | Low if specification-only | Neutral | No runtime data export is introduced | Low | Architecture reference |
| Provider-native schemas + small adapters | Exact for real returned data | Minimal | Excellent | Narrowest surface; no external telemetry | Medium per provider | Selected adapter strategy |
| tiktoken | Excellent for OpenAI preflight estimates | One wheel | Windows wheels / Python 3.11 supported | Local-only; prompt text is not persisted | Low | Direct dependency, estimate only |

## Security and license review

- Telemetry contains numeric counts, identifiers, role/model/provider, timing and cost only. It
  excludes prompts, assistant content, hidden reasoning, raw memory, secrets and API keys.
- SQLite stays local under `runtime/usage/usage.sqlite`; no OpenTelemetry exporter is enabled.
- MIT/Apache-2.0 dependencies are compatible with the current distribution model. No GPL/AGPL
  component or model weight is copied. Third-party model usage always passes the existing gateway.
- LiteLLM and Prime Agent were not copied or forked; their large runtimes and different governance
  boundaries make direct integration riskier than narrow adapters.

## WHY_CUSTOM_IMPLEMENTATION

The small reconciliation/store/policy layer is custom because no candidate simultaneously preserves
AI Team OS provider adapters, approval/budget/audit boundaries, privacy-minimal local persistence,
task/agent attribution, and deterministic structured checkpoints. Mature capabilities are retained:
provider-native usage, tiktoken estimation, SQLite, Tauri sidecars, and existing LangGraph checkpoints.
