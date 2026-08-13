# PRODUCT-02 Final Receipt

PHASE: PRODUCT-02  
STATUS: READY_FOR_CHIEF_REVIEW  
PRODUCT_BASELINE: VALIDATED  

## Baseline

- Previous HEAD: `7963efd0f63314fa0b70aae6c2f101d9862427bf`
- Current working tree: implementation and acceptance artifacts complete; no commit created.
- Real provider: DeepSeek Official production connection.
- Fake fallback during real gates: 0.

## Planner

- Planning envelope: task shape, capability allowlist, min/max subtasks, available tools,
  token budget, model-call budget and one bounded plan repair are deterministic inputs.
- STANDARD max subtasks: configured 4; maximum observed in 10 real STANDARD traces: 2.
- Capability routing: deterministic `RoleRouter`; governance roles cannot become executable
  subtasks.
- Invalid role prevention: plan validation rejects unknown, disabled or non-executable roles.
- Real calibration: 10/10 plans bounded, executable, budget compliant and free of unnecessary
  Executor use on read-only work.
- Average subtasks in the real STANDARD calibration: 2.0.

## Researcher

- Tool schema: complete required/optional/type/example contract generated from each `ToolSpec`.
- Argument validation: unknown fields filtered; aliases normalized; deterministic missing-field
  repair is bounded per tool and per subtask.
- Calibration suite: 20 GitHub argument variants passed through the real ToolGateway contract.
- Covered: sort/order, boundary page sizes, whitespace normalization, unknown fields, missing
  required arguments, empty results, rate limiting, malformed JSON and invalid queries.
- Dependency evidence: chained Researcher evidence is preserved as one verified claim per unique
  evidence reference; no duplicate probe loop is required.

## Reviewer

- Contract: PASS / PASS_WITH_NOTES / REWORK / BLOCK with strict nested schemas.
- Calibration: 18/18 real Reviewer cases.
- Distribution: PASS 5, PASS_WITH_NOTES 5, REWORK 5, BLOCK 3.
- False reject rate on explicit PASS cases: 0%.
- Deterministic priority: security, tests, patch validation and evidence integrity remain above
  model Reviewer judgment.
- Truncation calibration: only explicit prompt-window duplication issues may be downgraded; valid
  `rework_items` are never rewritten into notes.

## Rework

- STANDARD max: 1 targeted rework.
- COMPLEX max: 2 targeted reworks.
- Local rework: re-dispatches only rejected subtasks.
- No-progress detection: repeated failure signatures trigger deterministic replan/stop.
- Supervisor replan: bounded to 2; superseded work is excluded from dispatch/review/finalization.
- Blind retry: 0 in final real gates.

## Cost Governor

- STANDARD role limits: Supervisor 2, Planner 2, Researcher 4, Executor 3, Reviewer 2.
- Soft threshold: 12 calls.
- Recovery threshold: 16 calls.
- Hard stop: 20 calls unless the user explicitly supplies a lower bound; no production path was
  raised to 100.
- Parallel reservations are atomic.
- Real-gate calls: core 47; SIMPLE 27; STANDARD 42; COMPLEX 28; 10-turn 35; Reviewer 19.

## Real Core

- One-round gate: 3/3.
- Consecutive gate: 9/9.
- Average calls: 5.22.
- Highest calls in the 9 samples: 7.
- Tokens: 107,803.
- Recorded cost: 0.017228.
- Fake fallback: 0.

## Real Simple

- Passed: 10/10.
- Average calls: 2.7 (target <= 4).
- Median / P95: 3 / 3.
- Average tokens: 3,662.8.
- Average latency: 6.89 s.
- Rework rate: 0.
- Fast path: deterministic plan, one Researcher, no model Planner or model Reviewer.

## Real Standard

- Passed: 9/10 (target >= 9/10).
- Average calls: 4.2 (target <= 12).
- Median / P95: 4 / 5 (target P95 <= 20).
- Average tokens: 5,891.
- Average rework: 0 (target <= 1).
- Failure retained: B09 stopped with `budget_exceeded` after the Researcher role reached its
  frozen four-call limit; it was not silently retried or removed.

## Real Complex

- Pre-gate after root-cause fix: 3/3 (target >= 2/3).
- Final: 5/5 (target >= 4/5).
- Average calls: 5.6; P95 7.6.
- Average tokens: 10,478.2.
- Average rework: 0.
- Earlier failed runs remain in event/audit storage; the shared dependency-evidence loss was fixed
  before the final full rerun.

## Real 10-Turn

- Turns 1-10: all passed.
- Context-dependent references resolved: second item, compare with our project, continue, first
  plan item and recent result.
- Turn 5 no-write confirmation: 0 model calls.
- Turn 8 explicit implementation: isolated `sample-python` workspace, source fixture unchanged.
- Turn 9 result replay: 0 model calls.
- Average calls: 3.5; average rework: 0.1.
- Full history is not injected; Working Context, selected item, pending plan and bounded recent
  grounding are persisted in the session layer.

## Completion and Failure UX

- Empty completed result: blocked by `ProductCompletionValidator`.
- Research: requires non-empty result, claims, requested quantity where explicit, and evidence.
- Code change: requires implementation metadata, passing tests and final review.
- Code analysis: rejects unauthorized writes.
- Windows action: requires verified action metadata.
- Provider error mapping covers auth, timeout, rate limit, budget, server, model and schema classes.
- Failure details include stage, agent, code, root cause, recovery and final decision.
- First failed samples are retained; reruns do not delete them.

## Security

- Hardcoded benchmark routing: not found in production code.
- Unsupported executable roles: 0 in final gates.
- Prompt injection cannot expand roles, tools, budget, workspace or permission mode.
- Secret/UAC/safety-kernel/STOP invariants remain outside model authority.
- Checkpoint deserialization uses an explicit local-state type allowlist.
- Real implementation writes occurred only in isolated workspaces; the source fixture has no diff.
- Fake fallback: 0.
- Budget runaway: 0.

## Engineering Regression

- Backend pytest: PASS (full suite; 2 environment-dependent skips).
- Ruff: PASS.
- Mypy: PASS, 116 source files checked.
- Pip check: PASS.
- Frontend typecheck: PASS.
- Frontend ESLint: PASS.
- Frontend Vitest: PASS, 5 files / 10 tests.
- Frontend production build: PASS.
- NPM audit: 0 vulnerabilities.
- Known non-blocking warning: Starlette warns that its current `httpx` TestClient compatibility
  layer is deprecated.

## Open Source Reuse

- Projects researched: LangGraph, Prime Agent, LiteLLM, Agent Skills Context Engineering.
- Direct dependencies: LangGraph (existing MIT dependency) for graph routing, Send fan-out/fan-in
  and SQLite checkpoint integration.
- Adapter integrations: no new third-party runtime adapter was required for this phase.
- Components reused: LangGraph checkpointer/serializer contracts and the repository's existing
  GitHub/ToolGateway/Workspace infrastructure.
- Architecture references: Prime Agent bounded autonomy and quality gates; Agent Skills Context
  Engineering role-scoped context patterns.
- Rejected projects: LiteLLM for PRODUCT-02 because its broader provider/cost surface was not the
  missing reliability layer and would increase integration scope.
- License review: researched projects are MIT; no GPL/AGPL code copied; no full fork.
- Custom code still required: AI Team OS planning envelope, role/capability router, workflow cost
  governor, tool repair contract, completion validator and governed session context.
- Estimated avoided custom work: retained LangGraph graph/checkpoint/fan-out primitives instead of
  building a scheduler, persistence engine and parallel join layer.

## Final Decision

- Blind Retry: 0.
- Fake Fallback: 0.
- Unexplained Failure: 0.
- Empty Completed Result: 0.
- Unsupported Role: 0.
- Budget Runaway: 0.
- Blocking: 0.
- High: 0.
- Medium: 0.
- Low: 1 non-blocking third-party test-client deprecation warning.

`PRODUCT_BASELINE_VALIDATED`
