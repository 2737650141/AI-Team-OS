# Memory context contract

`TaskState.memory_refs` is the stable checkpoint contract. It contains IDs and versions only.

`ContextBuilder` asks a memory loader at each supervisor, planner, researcher, executor, or reviewer call. Resolution requires: memory exists; status is active; version matches; memory type is allowed for the role; memory is enabled. A failed condition silently excludes the record and is never recovered from checkpoint text.

Supervisor receives continuity and user preferences; planner receives project constraints and workflow preferences; researcher/executor receive project and procedural constraints; reviewer receives project acceptance and user output preferences. Each injected block states that the current task instruction has priority.

The runtime event `memory_used` exposes only governed trace fields. Hidden reasoning and credentials are never emitted.
