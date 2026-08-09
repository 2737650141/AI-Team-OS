# Memory privacy

Memory is local and user controlled. Secret-like content is scanned and rejected before proposal persistence. `privacy_level=secret` is never accepted. Sensitive content and sensitive-topic inference cannot become ordinary memory automatically.

Exports omit secret and forgotten records and omit internal hashes. “Forget” wipes value, normalized value, tags, and FTS content, increments the version, and retains only a non-content audit tombstone. Project and global scope are explicit; all queries include user isolation.

API responses never expose credentials. Custom Provider keys live only in the session store or Windows DPAPI secure store. Provider SQLite rows contain configuration and model metadata only.
