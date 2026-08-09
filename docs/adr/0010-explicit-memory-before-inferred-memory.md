# ADR 0010: Explicit memory before inferred memory

Status: Accepted

Decision: add a local governed memory module around the existing graph. Models, tools, documents, and task observations may propose but cannot write active user semantics or preferences. Explicit user statements and explicit confirmation precede inferred adaptation.

Consequences: continuity is explainable and reversible without a LangGraph rewrite. Repeated low-risk signals still produce a proposal only. Automatic personalization is intentionally conservative.
