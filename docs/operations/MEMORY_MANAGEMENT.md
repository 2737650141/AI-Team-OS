# Memory management operations

Web UI is the recommended control path. Advanced commands are:

```text
ai-team-os memories
ai-team-os memory-show <id>
ai-team-os memory-search <query>
ai-team-os memory-proposals
ai-team-os memory-confirm <id>
ai-team-os memory-reject <id>
ai-team-os memory-edit <id> <value>
ai-team-os memory-forget <id>
ai-team-os memory-export
ai-team-os memory-health
```

Back up with `MemoryStore.backup()` before operational migration. Restore verifies SQLite integrity and uses the SQLite backup protocol to avoid stale WAL state. `memory-health` reports schema version, integrity, FTS5, record count, and pending count.

Demo: submit “这个项目以后都优先使用中文，并且修改代码前先给我看 Diff。” Confirm the two proposals in Memory Center, then create a second task in the same project. Task Detail explains which confirmed memories were loaded.

For a custom Provider, create metadata first, save the credential, test, discover models, select a default and role routes, then save. Public providers must use HTTPS. Loopback/private/link-local/metadata addresses are rejected unless the provider is explicitly local.
