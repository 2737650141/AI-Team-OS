# Controlled Memory architecture

M4-A adds governed continuity to the existing modular monolith. It does not replace LangGraph, the checkpoint store, or the Agent graph.

The boundary is `app/memory/`: typed records and proposals, deterministic policy, SQLite persistence, FTS retrieval, context budgeting, and usage traces. A model or task may only produce a proposal. Only deterministic governance and an explicit user confirmation can create an active semantic or preference memory.

Memory classes are working, episodic, semantic user, project, and procedural preference. Status transitions are `proposed → active`, `active → superseded|expired|forgotten`, with rejected and quarantined proposal outcomes. Privacy levels are public, personal, sensitive, and secret. Secret values are rejected before any database write; sensitive inference is quarantined.

The database is `runtime/memory/memory.sqlite`. It contains memories, proposals, events, links, confirmations, usage, preference signals, settings, schema metadata, and an FTS5 index. Writes use transactions, parameterized SQL, WAL, integrity checks, deterministic unique constraints, backup, and restore.

Task checkpoints store only `{memory_id, version}` references. Every role resolves those references against the current database status. This is the invariant that prevents a forgotten, expired, or superseded value from returning when an old checkpoint resumes.

Custom OpenAI-compatible providers are persisted separately in `runtime/providers.sqlite`. Provider configuration and discovered model metadata may persist; credentials never do. Dynamic credential keys use `custom_provider.<id>.api_key` in SecretResolver.
