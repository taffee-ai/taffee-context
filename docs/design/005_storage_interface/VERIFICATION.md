# 005 Storage interface: verification

Run on the Ubuntu execution host (5.7 GB RAM, 4 threads). Stack: `infra/compose.yaml` (graphdb, ingestion, mcp). Test database: a throwaway Neo4j 5.26 on port 27687.

## 1. Parity with the MCP baseline (requirement R6)

The check: the same 13 calls (repos, stats, node, explain, neighbors, affected, hubs, community, path, query, search, code, pack), compared byte for byte with a baseline captured before the change, including after kill-and-restart cycles.

**Not yet verified on a public repository.** The earlier run is not published; this check is to be repeated against FastAPI.

## 2. Provider and view tests (R1, R3, R4, R5, R7)

`python/tests/`, run in the MCP image with the database tests enabled:

- `test_read_store`: the read view exposes reads only; the snapshot ID matches the TypeScript format; resolution by newest, by prefix, ambiguous prefix and unknown repo; staged snapshots invisible to every read; repo listing (default and all commits); stats; exact then suffix node lookup; neighbours; graph read with native properties; community; shortest path with direction; file check; semantic state; scoped and global chunk search; chunk symbols.
- `test_neo4j_store`: the write path (stage, unchanged, conflict, publish, idempotent publish, missing, summary).
- `test_storage_factory`: provider selection.

Result: **31 of 31 pass.**

## 3. Existing suites (Level 5)

- TypeScript: typecheck passes; **41 of 41 tests pass**, 0 skipped (including the database tests).

## 4. Problems found and fixed

See IMPLEMENTATION.md, "Defects found while implementing". Each has a test that fails without the fix.

One problem was in the harness, not the product: the first restart cycle sent its first request before the MCP port was listening, because the script treated a startup line from the previous run as "ready". The script now waits for the port. No product change was needed.

## 5. Not verified in this step

- The read-only database user (D-005-4). The MCP service still runs as the Neo4j admin user.
- Performance on large repos. The readiness check adds one lookup per read; not measured.
- The context pack (phase 2).
