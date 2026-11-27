# Verification record

Only fixtures and public repositories are used here. Everything runs in Docker containers on a test laptop; nothing is built or tested on the editing machine.

## Current test suite (2026-11-15)

Images: `Dockerfile.base` (`taffee-base:dev`: Node 20.20.2, Python 3.12.15, git, `graphifyy==0.9.51`), `Dockerfile.ingest` (`taffee-ingest:dev`) and `context/serving/mcp/Dockerfile` (`taffee-mcp:dev`). Database: Neo4j 5.26.0-community.

| Suite | Command | Result |
|---|---|---|
| Typecheck | `npm ci && npm run typecheck` | 0 errors |
| TypeScript, no database | `npm test` | 41 tests: 31 pass, 10 skipped (need the database), 0 fail |
| TypeScript, with database | `TAFFEE_NEO4J_TEST=1 npm test` | 41 of 41 pass |
| Python storage, with database | `TAFFEE_NEO4J_TEST=1 python -m pytest python/tests` | 33 of 33 pass |
| MCP unit tests | `python -m pytest tests/test_turbo_distiller.py tests/test_turbo_jev.py tests/test_turbo_units.py tests/test_cli_pack.py tests/test_session_binding.py` (in `taffee-mcp:dev`) | 75 of 75 pass (2026-11-27, mcp 1.30.0) |
| Token script | `gen_tokens.sh` with and without caller names | default callers `agent-1 agent-2 test`; custom names written; existing file not overwritten |

## Public repositories (2026-11-14)

Ingested and embedded for the public eval, at the commits pinned in `eval/repos.yaml`:

| Repository | Nodes | Edges | Ingest | Chunks | Links | Cut by 2048-token cap | Embedding | Embedder peak | State |
|---|---|---|---|---|---|---|---|---|---|
| FastAPI `913c68062c89` | 9,342 | 18,919 | 59.2 s | 1,638 | 7,184 | 1 | 4,270 s | 1,849 MB | `ready` |
| NestJS `2731c18054fb` | 15,185 | 36,714 | 88.4 s | 2,600 | 9,581 | 0 | 5,218 s | 1,606 MB | `ready` |

On a laptop with an Intel Core i3-1000NG4 (2 cores / 4 threads); ingest in a 2-CPU / 2.5 GB container, embedding in a 2-CPU / 3 GB no-swap container. Details: 001 and 002 BENCHMARKS.md.

The MCP server then served the full FastAPI eval (1,080 agent runs using `query_graph`, `get_node`, `explain`, `affected`, `god_nodes`, `semantic_search` and `read_code`) with 0 errors. Results: `eval/results/2026-11-14-fastapi/REPORT.md`.

---

# Structural code graph (feature 001)

## Operator CLI on a 3-function fixture repo

Functions `callee`, `caller` (calls `callee`), `top` (calls `caller`).

- `ingest`: `created`, 4 nodes, 5 edges. Repeat `ingest`: `unchanged`, identical hashes.
- `verify` against the saved snapshot: passed.
- `query resolve`, `find_symbol caller`: correct snapshot and symbol. `get_callees(caller)` returned `callee`, `get_callers(callee)` returned `caller`, `get_callers(caller)` returned `top`.
- Snapshot edges, source to target: `caller -> callee calls`, `top -> caller calls`. Query results match that direction.

## Tamper checks on `verify`

- Edited label in the saved snapshot file: `verify` failed ("Stored snapshot does not match the source artifact").
- Deleted one edge in Neo4j: `verify` failed.
- Changed one node's `label` property in Neo4j: **`verify` still passed.** `verify` compares the stored content hash, artifact hash and counts; it does not recompute the hash from the stored node and edge properties, so property edits that keep counts unchanged are not detected.

## Assumptions checked

- `graphify extract <dir> --code-only --no-viz --out <dir>` works in 0.9.51 and the extractor reads `graph.json` from the `--out` directory.
- Edge direction is correct on the fixture; it was not diffed edge by edge against Graphify's own `graph.json`.
- The validator rejects dangling edges (unit test). Duplicate links, community and native order are covered by unit tests.
- Atomic ingest, concurrency, immutable conflict, repo and version scoping and rollback are covered by live tests. Symlink refusal and exact-commit extraction (untracked files excluded) are covered by live tests.

## Known gaps

- Calls made from inside nested functions are not recorded as caller edges (found in the public eval on FastAPI).
- Submodule refusal and the 32 MiB output bound have no test.
- No comparison against external baseline counts.
- Peak memory of ingest was not recorded; it is collected from the next run on (`eval/DESIGN.md` section 6.5).
- `verify` limitation above is unfixed; fixing it means recomputing the graph hash from Neo4j.

---

# Semantic chunk layer (feature 002)

## Environment

- Model `jinaai/jina-embeddings-v2-base-code` (768 dimensions; the model card lists Apache-2.0; the remote-code repo `jinaai/jina-bert-v2-qk-post-norm` shows no license tag), revision `516f4baf13dec4ddddda8631e019b5737c8bc250`, remote-code revision `3baf9e3ac750e76e8edd3019170176884695fb94`.
- Weights and remote code are downloaded once, at image build, into `HF_HOME=/hf`; the image and the embedder child process set `HF_HUB_OFFLINE=1`.

## Fixture (3 Python files, real model)

- `chunk-embed`: 3 chunks, 0 truncated, 11 links, model load 4.3 s, embedding 6.6 s, peak RSS 1247 MB. Repeat run: `unchanged`.
- Search (top 3 of 3): "retry a failed payment with backoff" ranked `payments.py` first at 0.879; "check a user's password" ranked `auth.py` first at 0.820; "read rows from a csv file and add up a column" ranked `csvtools.py` first at 0.881. The off-topic query topped out at 0.627.
- Semantic live tests use a deterministic fake embedder, so they exercise the real loader, vector index and search without the model: idempotent re-run, an interrupted run that is not searchable, resume, and lease refusal.

## Bugs found and fixed

- `chunkSource` trusted its caller to filter files; it now filters itself.
- `initializeSchema` raced when two processes created the vector index; it now tolerates the equivalent-index error.
- The embedder's 30-minute timeout was too short for a real repository; it is configurable (default 2 hours).
- The offline cache lacked a `main` ref that the model's remote code looks up; the prefetch step sets it.
- A container with no memory limit could freeze the host; model containers run with a no-swap limit.
- Very long chunks need a lot of memory; a token cap (`EMBED_MAX_TOKENS`) is part of the immutable config.
- Rows were saved only after the process exited; they are saved every 15 seconds and the process is restarted every 100 chunks.
- Search could be crowded out by other snapshots' vectors in the shared index; an exact-scan fallback was added.
- A live test's 700-vector insert starved a structural test on a one-CPU Neo4j; tests run serially.

## Known gaps

- Search quality has no labelled evaluation.
- Chunk text is not stored, so search returns locations; `read_code` reads the lines from Git.
- `verify` does not cover the semantic layer.
- Each snapshot records its own token cap; search across repositories embedded with different caps mixes them.

---

# MCP server

`context/serving/mcp/` is a read-only MCP server over this schema: bearer-token auth, per-caller rate limit, error sanitizing, token budgets, and the tools listed in its README. `query_graph`, `affected` and `god_nodes` run Graphify's own code on a graph rebuilt from the stored original Graphify objects (`nativePropertiesJson`, `nativeOrder`).

## Verified

- The public eval used the server live on FastAPI for 1,080 runs with 0 errors (see above).
- `run_tests.sh` starts a low-limit server and checks the rate limit.
- Unit tests for the pack builder, scorer, Laya and Qwen adapters and the client run on mock data (68 of 68).

## Known gaps

- No live test of every tool against a public fixture repository is included yet, so tool-by-tool behaviour (auth failures, paging, path attacks on `read_code`, error sanitizing) and parity with Graphify run directly are not re-verified here.
- No third-party agent client was tested; only the test client and the bundled client, both built on the MCP Python package.
- With a self-signed certificate, clients must be told to trust it.
- Authentication is a clear-text token per caller: no per-user permissions, no audit log, no Git provider adapter (`read_code` reads a local clone).
- Load and concurrency were not tested beyond the rate-limit check; the model is loaded once and shared by all callers.

---

# MCP turbo (feature 003, experimental)

See [003_context_mcp_turbo/README.md](003_context_mcp_turbo/README.md). Verified: unit tests on mock data (flag isolation, mutual exclusion of the Laya and Qwen layers, token-budget cap, fallbacks), and model-only memory and timing in its BENCHMARKS.md. Not verified: any benefit to agents.
