# ADR 0012: Memory provenance and versioning

Status: Accepted

Decision: every memory records source type/reference, scope, confidence, privacy, confirmation, version, retention, timestamps, and supersession links. Task checkpoints persist only memory ID and version; each role resolves current status before use.

Consequences: the UI can explain why a fact is known and where it was used. Old checkpoints cannot resurrect forgotten, expired, or superseded content. Conflicts create an auditable version chain instead of silent overwrite.
