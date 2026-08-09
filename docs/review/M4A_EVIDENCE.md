# M4-A evidence

Branch: `phase-4a/controlled-memory`

Baseline: UI-02 `3adb673d9b3800340221fe4cdf89f7b50b57f64f` was fast-forward merged to `main`; this branch was created from that exact commit.

Implemented surfaces:

- governed SQLite/FTS memory, proposals, conflicts, TTL, true forgetting, backup/restore;
- checkpoint reference contract and per-role context/trace;
- Memory Center, task explanation, settings controls, bilingual copy;
- custom Provider CRUD, credentials, test/discovery/refresh, model search/routing;
- SSRF and poisoning defenses, Demo mode, APIs, and CLI.

Automated evidence is recorded by `tests/test_memory_system.py` and `tests/test_custom_providers.py`. Full Python, Ruff, TypeScript, ESLint, Vitest, production build, browser journeys, source/secret scans, and final commit are recorded in the final delivery receipt.

10,000-record benchmark (`scripts/benchmark_memory.py`, Windows local run): 6.964 s fixture insertion, 49.568 ms FTS search returning 100 bounded results, SQLite integrity `ok`. This is a simple acceptance benchmark, not a production throughput claim.

Final automated run: all Python tests passed with two intentional skips; Ruff passed; Mypy passed for 61 source files; TypeScript, ESLint, seven Vitest cases, and the Vite production build passed.

Codex in-app browser acceptance: C-M01 through C-M07 passed. Confirmed memory survived refresh and appeared in the next task with role/reason/version/token traces; Project A memory produced zero context in Project B; forgotten content disappeared from later context; disabled memory read and wrote nothing; synthetic secret and external-injection text produced no memory; Chinese and English surfaces passed with zero browser console errors.

Third-party browser acceptance used only the isolated non-network Provider. Add, credential save, test, discovery, refresh, search, default/role selection, save, replace credential, remove credential, and delete all passed. No real Provider was tested, altered, or removed.
