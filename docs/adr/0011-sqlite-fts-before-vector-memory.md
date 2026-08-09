# ADR 0011: SQLite FTS before vector memory

Status: Accepted

Decision: use the existing local SQLite operating model plus FTS5, deterministic scope filters, stable scoring, and bounded role context. Do not introduce a vector database in M4-A.

Consequences: storage, backup, restore, integrity, provenance, and user deletion remain inspectable. The 10,000-record acceptance benchmark remains responsive. Semantic similarity beyond lexical retrieval is deferred until evidence justifies its complexity.
