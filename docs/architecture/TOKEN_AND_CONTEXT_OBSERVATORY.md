# Token & Context Observatory

M6-P2 records model usage at the only authoritative boundary: `ModelGateway`. Provider
responses are normalized into `NormalizedModelUsage` and stored locally in
`runtime/usage/usage.sqlite`.

## Truth labels

- `REPORTED`: returned by the provider for the completed request.
- `ESTIMATED`: a local tokenizer or bounded character estimate, shown with `≈`.
- `UNAVAILABLE`: the provider and local adapter cannot establish a defensible value.

Cached input is a subset of input and reasoning is a subset of output, so neither is added to
the total a second time. Anthropic cache-create/cache-read values are reconciled into inclusive
input according to Anthropic semantics. Unknown prices and context windows remain `NULL`.

## Context policy

Capabilities come only from provider metadata, an official adapter, a user setting, or a verified
model profile. The default compaction threshold is 80%. At threshold, the gateway builds a
structured checkpoint containing the user goal, constraints, decisions, current work, open issues,
IDs, memory references, edited files, test failures, reviewer requirements, and approval state.
It never persists raw chat history or hidden reasoning as usage telemetry.

`context_compaction_started` and `context_compaction_completed` events expose before, after,
freed tokens, role, model, and duration. The policy can vary by role without changing callers.

## Storage and retention

SQLite rows contain counts, identifiers, timing, source labels, and optional cost only. Prompts,
responses, secrets, API keys, memory bodies, and chain-of-thought are excluded by schema. Retention
is user-controlled at Settings → Usage history: 7, 30, 90 days, or forever.

