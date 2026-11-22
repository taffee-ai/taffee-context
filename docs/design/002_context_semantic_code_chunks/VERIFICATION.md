# Verification: semantic code chunks

Status: implemented and verified on the designated test host between 2026-10-06 and 2026-10-07. Full evidence, commands and logs-as-prose are in `docs/design/verification.md` (sections "Semantic chunk layer (feature 002)" and "Update 2026-10-07"). This page is the summary and the release-gate view.

## Environment

- Test image `Dockerfile.base`: Node 20.20.2, Python 3.12.15, graphifyy 0.9.51, torch 2.8.0+cpu, transformers 4.57.1.
- Model `jinaai/jina-embeddings-v2-base-code` (768 dimensions), model revision `516f4baf13dec4ddddda8631e019b5737c8bc250`, remote-code revision `3baf9e3ac750e76e8edd3019170176884695fb94`, baked into the image, run offline.
- Neo4j 5.26.0-community (vector index syntax accepted), 1.5 GB container limit.
- Host: 4 threads, about 5.8 GB RAM, swap nearly full. An old test laptop, so slow runs are expected.

## Results

| Check | Result |
|---|---|
| Typecheck | 0 errors |
| Full suite with live Neo4j | 28 of 28 pass, 0 skipped (4 structural unit, 2 structural live, 15 chunk and embedder unit, 7 semantic live), run serially |
| Fixture (3 Python files, real model) | 3 chunks, 11 links, load 4.3 s, embed 6.6 s, peak RSS 1247 MB; repeat run `unchanged` |
| Fixture search | Right file first for three on-topic queries (0.879, 0.820, 0.881); off-topic topped out at 0.627 |
| Public repos (2026-11-14) | FastAPI: 1,638 chunks, 7,184 links, 1 cut by the 2048-token cap. NestJS: 2,600 chunks, 9,581 links. Both `ready` |
| Offline | Model loads and runs with no Hugging Face access |
| Concurrent builder | Second launch refused while the lease is held |
| MCP `semantic_search` | Served every `semantic_search` call in the public eval on FastAPI (1,080 runs, 0 errors) |

## Bugs found by verification and fixed

- `chunkSource` trusted its caller to filter files (a `.min.js` file got through a unit test); it now filters itself.
- `initializeSchema` raced when two processes created the vector index; it now tolerates the equivalent-index error.
- The embedder's 30-minute timeout aborted a real repository run; it is now configurable (default 2 hours).
- The offline cache lacked a `main` ref that the model's remote code looks up; the prefetch step now sets it.
- Container with no memory limit froze the host; model containers now run with a no-swap limit.
- Very long chunks need a lot of memory; a token cap (`EMBED_MAX_TOKENS`) is part of the immutable config.
- Rows were saved only after the process exited; they are now saved every 15 seconds and the process is restarted every 100 chunks.
- Search could be crowded out by other snapshots' vectors; exact-scan fallback added.
- A live test's 700-vector insert starved a structural test on the one-CPU Neo4j; tests now run serially.

## Known gaps (not verified)

- Each snapshot records its own token cap; search across repositories embedded with different caps mixes them.
- Search quality rests on a handful of queries judged by reading results; there is no labeled evaluation.
- Chunk text is not stored and the CLI does not read code from Git for results.
- Submodule refusal and the collection bounds have no test.
- `verify` does not cover the semantic layer.
- MCP `semantic_search` across all repositories uses the shared index without the exact-scan fallback.
- Neo4j was once stopped uncleanly (exit code 137) during a container swap; it recovered, but unclean stops were not otherwise examined.

## Release gate

| Gate | State |
|---|---|
| Typecheck clean and full suite passes with live Neo4j | Met (28 of 28) |
| Fixture and a real repository chunked, searched and repeat-run as `unchanged` | Met |
| Interrupted run is not searchable and resumes correctly | Met |
| No source leaves the environment; run is offline | Met for the model; the pinned code revision is fetched once at image build |
| Config and content immutability enforced | Met (unit and live tests) |
| Retrieval quality measured against labeled data | **Not met** |
| Behaviour beyond 2,600 chunks per repository (NestJS) | **Not tested** |
