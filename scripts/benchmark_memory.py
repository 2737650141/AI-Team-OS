"""Repeatable 10k-record FTS benchmark for M4-A evidence."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from app.memory.models import MemoryRecord, utc_now
from app.memory.store import MemoryStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10_000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(
        prefix="ai-team-memory-bench-", ignore_cleanup_errors=True
    ) as temp:
        store = MemoryStore(Path(temp) / "memory.sqlite")
        now = utc_now()
        started = time.perf_counter()
        with store._connect() as conn:  # benchmark fixture: one explicit transaction
            for index in range(args.count):
                value = f"architecture guideline number {index} for project alpha"
                normalized = store.normalize(value)
                record = MemoryRecord(
                    memory_id=f"bench-{index}",
                    project_id="alpha",
                    memory_type="project",
                    subject=f"guideline-{index}",
                    predicate="requires",
                    value=value,
                    normalized_value=normalized,
                    confidence=0.9,
                    status="active",
                    privacy_level="public",
                    source_type="imported_profile",
                    source_ref="benchmark",
                    created_at=now,
                    updated_at=now,
                    confirmation_required=False,
                    confirmed_by_user=True,
                    content_hash=store.content_hash(
                        f"guideline-{index}", "requires", normalized, "alpha"
                    ),
                    tags=["architecture", "benchmark"],
                )
                store._insert_memory(conn, record)
                store._sync_fts(conn, record.memory_id)
            conn.commit()
        insert_seconds = time.perf_counter() - started
        search_started = time.perf_counter()
        result = store.search("architecture project alpha", project_id="alpha", limit=100)
        search_ms = (time.perf_counter() - search_started) * 1000
        print(
            json.dumps(
                {
                    "records": args.count,
                    "insert_seconds": round(insert_seconds, 3),
                    "search_ms": round(search_ms, 3),
                    "results": len(result),
                    "integrity": store.health().integrity,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
