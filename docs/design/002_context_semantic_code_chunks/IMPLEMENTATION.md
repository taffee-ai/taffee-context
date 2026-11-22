# Implementation: semantic code chunks (as built)

This is a map of the code that exists, not a plan. Design rationale is in DESIGN.md and DECISIONS.md.

## Module map

| File | Lines | Exports and what they do |
|---|---|---|
| `context/ingestion/chunks/chunker.ts` | 136 | `SEMANTIC_CONFIG` (pinned model, 768 dims, 150 lines, 8000 chars, 8192 tokens, `.js .jsx .py .ts .tsx`), `SEMANTIC_LIMITS`, `chunkId`, `isChunkable`, `chunkSource`, `computeLinks`, `semanticConfigHash`, `semanticContentHash`, `configFromEnv`, `decideSemanticStart` |
| `context/ingestion/chunks/collect.ts` | 45 | `collectSource`: clone `--no-local`, checkout detached SHA, verify HEAD, refuse submodules and symlinks, walk files (skips `.git`, `node_modules`), enforce file count and size bounds |
| `context/ingestion/embeddings/embed_chunks.py` | 80 | Loads the pinned model with `trust_remote_code` and revisions; per chunk: count tokens, encode with `max_length`, write and flush one JSON line `{id, embedding, tokens, tokenTruncated}`; writes a meta file (load and embed seconds, torch and transformers versions, peak RSS) |
| `context/ingestion/embeddings/run-embedder.ts` | 153 | `validateEmbedding`, `EmbeddingReader` (incremental JSON-lines reader), `readEmbeddingRows`, `pythonEmbedder` (spawn, 15 s drain timer, timeout, per-segment processes) |
| `context/ingestion/embeddings/prefetch_model.py` | 33 | Image-build step: downloads the pinned revisions into `HF_HOME`, points the cache's `main` ref at the pinned commit |
| `context/ingestion/load/neo4j-semantic-loader.ts` | 177 | `buildSemanticLayer` and the private `begin`, `writeBatch`, `finalize`, `release`; `SemanticResult` |
| `context/retrieval/query/neo4j-search.ts` | 84 | `validateSearch`, `embedQuery`, `searchChunks`, `SEARCH_FETCH = 600` |
| `context/storage/neo4j/schema.ts` | 28 | `SCHEMA_V2`: chunk uniqueness constraint and the vector index |
| `context/cli.ts` | 105 | `chunk-embed <repoId> <repoPath> <sha>` and `search <repoId> <query> [sha\|-] [topK]` |
| `Dockerfile.base` | | Base image with Node, Python, Graphify, torch CPU and the baked model |

## Control flow in `buildSemanticLayer`

1. `collectSource` then `chunkSource` give the chunk plan.
2. Entities of the ready structural snapshot are read from Neo4j and `computeLinks` produces the links.
3. Config hash and content hash are computed.
4. `begin` runs in one write transaction under the repository write lock: it requires a ready structural snapshot, calls `decideSemanticStart`, refuses if another lease is live, deletes chunks on `restart`, writes the semantic properties and status `building`, and takes the lease. If the answer is `unchanged`, the function returns without loading the model.
5. Chunks that already have a vector are read back and skipped. The rest go to the embedder.
6. The embedder callback calls `writeBatch`, which re-checks that this owner still holds the lease, renews it, and `MERGE`s `ContextChunk` nodes with their vectors.
7. `finalize` checks stored counts against the plan, creates `DESCRIBES` links in batches of 500, checks the link count, then sets `semanticStatus = ready` and removes the lease in the same transaction.
8. Any error in steps 5 to 7 calls `release` (lease removed, status stays `building`) and rethrows.

## Embedder protocol

- Input file: JSON lines `{id, text}`; text must already be cut to the character cap.
- Output file: JSON lines `{id, embedding[768], tokens, tokenTruncated}`, flushed per chunk. An interrupted process leaves a valid prefix.
- The runner reads the file while it grows, keeps a half-written last line for the next read, and validates every row: dimension 768, finite numbers, id was requested, no duplicates, sane token fields. Output over 256 MiB is rejected.
- Child environment sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`; arguments are passed as an array, never through a shell.

## Search flow in `searchChunks`

Validate arguments, pick the newest ready snapshot (semantic-ready preferred), refuse if its semantic layer is not `ready`, embed the query with the same model, query the global index for 600 neighbours, keep this snapshot's, fall back to an exact cosine scan if crowded out, attach up to 10 entities per hit, return diagnostics (`method`, `fetched`, `matched`, `filteredOut`, `possiblyIncomplete`). The read transaction has a 5 s timeout.

## Using it

```bash
npm run context -- init-schema
npm run context -- ingest <repoId> <repoPath> <sha> -        # structural snapshot first
npm run context -- chunk-embed <repoId> <repoPath> <sha>     # minutes to hours; resumable
npm run context -- chunk-embed <repoId> <repoPath> <sha>     # second run reports "unchanged"
npm run context -- search <repoId> "validate widget access" - 5
```

Run the model inside the container image, one model-loading container at a time, with `--memory` equal to `--memory-swap`. On a host with 2 GB or less to spare set `EMBED_MAX_TOKENS=2048`.

## Where the tests are

`context/testing/context-chunks.test.ts` (15 unit tests) and `context/testing/context-semantic-neo4j.test.ts` (7 live tests with a deterministic fake embedder). See TEST-CASES.md for what each one proves.

## Known implementation limits

- `semantic_search` across all repositories (MCP) uses the shared index without the exact-scan fallback.
- The CLI `search` returns locations; reading the code for a hit is not wired into the CLI.
- Layers built with different token caps coexist; each snapshot records its own config.
