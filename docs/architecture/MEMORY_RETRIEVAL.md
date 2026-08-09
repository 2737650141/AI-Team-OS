# Memory retrieval

Retrieval is deterministic: scope filter, active-status filter, role type allowlist, FTS5 match, stable score, fact de-duplication, then context limits.

Project matches outrank global memories. Confirmed facts gain priority; project facts, approval/security tags, confidence, and freshness contribute bounded scores. Each role has a memory-type allowlist. Default limits are 12 records, 1,200 estimated tokens, five per type, and eight per project.

Current task instructions are never placed inside memory and always remain the controlling input. If a task conflicts with a stored preference, the task wins. Search is user and project isolated and can include global records only deliberately.

Every selected record produces a usage row containing memory ID, version, role, reason, scope, estimated token count, run ID, and timestamp. Values are not copied into checkpoints.
