# Open Source Review — PRODUCT-02 Orchestration Reliability

Date: 2026-08-12

## Capability under review

PRODUCT-02 only addresses bounded multi-agent orchestration: constrained planning, tool-call argument validation and repair, calibrated structured review, local rework, workflow cost governance, context minimization, and product completion validation. It does not add agents or replace the existing LangGraph runtime.

## Review method

The review checked each candidate's README and architecture, license, release/activity signals, issues/security surface, dependency footprint, relevant source and examples/tests. Repository metadata was rechecked on 2026-08-12. No source code from the reviewed projects is copied into AI Team OS.

## Comparison

| Repository | Purpose | License | Activity reviewed | Relevant components | Windows / Python 3.11 | Reuse level | Decision |
|---|---|---|---|---|---|---|---|
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | Stateful, durable agent orchestration | MIT | 37k+ stars, hundreds of releases, active issues/PRs; current 1.2 line matches the project's dependency range | `StateGraph`, `Send`, reducers, checkpoints, interrupts, `RetryPolicy`, state snapshots, tests/examples | Python library; already passing on Windows/Python 3.11 in this repository | LEVEL 1 — Direct Dependency | Keep. Use graph/state primitives and deterministic routing; do not rewrite LangGraph. |
| [PrimeIntellect-ai/prime-agent](https://github.com/PrimeIntellect-ai/prime-agent) | Long-running coding/research harness | MIT | New but highly active; thousands of commits, active issues/PRs | Bounded autonomous mode, turn/token/time limits, quality gates, durable goals, compaction, explicit warning that a reached limit is not success | Primary installer targets macOS/Linux; architecture is not a drop-in fit for the Windows Python product | LEVEL 4 — Architecture Reference | Reuse bounded-autonomy and quality-gate ideas only. No fork and no dependency. |
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | Multi-provider SDK/gateway, routing, usage and cost tracking | Mixed repository surface; core is open source but commercial features are explicitly identified | 53k+ stars, frequent releases, large active issue/PR and security surface | Unified provider errors, callbacks, spend tracking, routing/retry policy | Supports Python, but adds a large dependency and operational surface | Rejected for this phase | Existing ModelGateway/Usage Observatory already cover the required boundary. Adding LiteLLM would expand provider scope and supply-chain risk during a reliability-only phase. |
| [muratcankoylan/Agent-Skills-for-Context-Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering) | Context curation patterns for agents | MIT | Active 2026 updates; modular skills and references | Signal-over-volume, role-specific context, progressive disclosure, context compression and evaluation patterns | Documentation/patterns are platform-neutral | LEVEL 4 — Architecture Reference | Apply role-focused context packs and context telemetry; do not import executable skills. |

## Detailed findings

### LangGraph

- README/architecture: low-level stateful orchestration, durable execution, interrupts and state inspection match the current architecture.
- License: MIT; compatible with this repository.
- Releases/activity: the upstream repository remains actively maintained; PRODUCT-02 stays within the already pinned `langgraph>=1.2,<2.0` range.
- Core source: `StateGraph`, `Send`, reducer and checkpoint primitives already underpin `app/graph.py`; upstream `RetryPolicy` is intentionally not used for semantic reviewer/tool retries because PRODUCT-02 requires classified, budgeted recovery rather than blind node retry.
- Security: LangGraph remains inside AI Team OS governance. It does not receive authority to bypass ToolGateway, ApprovalPolicy, SecretStore, workspace boundaries, audit, or STOP.
- Integration cost: lowest. The correct change is stricter state contracts and routing around the existing graph, not a framework migration.

Decision: retain as the only direct orchestration dependency.

### Prime Agent

- README/architecture: the useful pattern is bounded autonomous execution with explicit turn/token/time budgets and user-defined quality gates. Its documentation explicitly separates “limit reached” from “task succeeded”, which matches `ProductCompletionValidator`.
- License: MIT.
- Activity: very active but young, with a large change rate and open issue/PR volume.
- Dependencies/platform: persistent IPython, daemon/worker/kernel and TypeScript/Node packaging are a substantial architectural mismatch; official quick-start targets macOS/Linux.
- Security: upstream warns that model-generated Python and commands run with user permissions and are not a security sandbox. Direct adoption would conflict with AI Team OS governance requirements.

Decision: architecture reference only; copy no code. Reuse bounded budgets, durable progress, explicit quality gates and “budget exhausted is not success”.

### LiteLLM

- README/architecture: mature provider normalization, routing, retry/fallback, usage callbacks and spend management.
- License/security: the repository distinguishes commercial features and has a broad, fast-moving dependency/supply-chain surface. A 2026 package supply-chain incident means any future adoption needs a separate pinning, provenance, SBOM and credential-isolation review.
- Integration: AI Team OS already has `ModelGateway`, provider routing, secure secret resolution and usage accounting. Introducing LiteLLM now would duplicate responsibility and violate the “reliability only” scope.

Decision: rejected for PRODUCT-02. Reconsider only in a dedicated provider phase, behind a Level-2 adapter and governance boundary.

### Agent Skills for Context Engineering

- Architecture: context is treated as a finite attention budget; the recommended pattern is the smallest high-signal role-specific context plus on-demand detail.
- License: MIT.
- Relevant patterns: progressive disclosure, recent context plus structured summary, artifact-focused reviewer context, tool-schema clarity and per-role context metrics.
- Security: executable third-party skills are not adopted. External content remains untrusted data and cannot alter system policy.

Decision: architecture reference only.

## Reuse strategy

- Direct dependencies: existing LangGraph dependency only.
- Adapter integrations: none added in PRODUCT-02.
- Component reuse: existing Pydantic validation and LangGraph graph/checkpoint primitives.
- Architecture references: Prime Agent bounded autonomy and quality gates; Agent Skills role-context curation; LiteLLM error/usage taxonomy only.
- Rejected: full Prime Agent fork, LiteLLM dependency/proxy, any replacement of LangGraph.

## Security and license conclusion

All selected source licenses are permissive for architecture reference, but no third-party source is copied. Third-party behavior cannot bypass ToolGateway, Workspace/Sandbox, ApprovalPolicy, SecretStore, MemoryPolicy, audit, permission mode, or emergency STOP. Provider and tool failures are sanitized before persistence; secrets and raw credentials are excluded from events and benchmark artifacts.

## WHY_CUSTOM_IMPLEMENTATION

The missing logic is project-specific governance glue: `PlanningEnvelope`, capability-to-role routing against this registry, bounded argument repair against this ToolGateway, role-level call budgets, reviewer status semantics, local rework progress checks, and task-shape completion rules. Mature projects provide the primitives and patterns but cannot implement these AI Team OS contracts without importing an incompatible runtime or bypassing existing governance. The custom code is therefore limited to those gaps.

## Estimated avoided custom work

Keeping LangGraph and Pydantic avoids reimplementing graph scheduling, parallel fan-out/fan-in, state reducers, checkpoint persistence, interrupts and schema validation—several thousand lines of high-risk infrastructure. PRODUCT-02 remains a focused policy/contract layer rather than a new orchestration engine.
