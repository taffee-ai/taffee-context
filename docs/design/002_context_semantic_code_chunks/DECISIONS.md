# Decisions

- **Code is TypeScript plus one small Python script**, designed specifically for TAFFEE's data model and readiness lifecycle. Conventions chosen: window size (150 lines), character cap (8000), extensions, chunk id, line-containment links, over-fetch of 600, model and `transformers` pin.
- **Separate semantic state** (`semanticStatus`, config hash, content hash, lease) instead of touching `ready` or the structural hash.
- **Content hash excludes vectors**: float output is not guaranteed bit-identical across hardware.
- **Lease** on the snapshot so two builders cannot load the model at once; released on failure; renewed on every batch write.
- **Resume by skipping chunks that already have a vector**; links are created only in the final transaction so a partial build has none.
- **Pinned revisions** match verified stable commit SHAs for `JINA_MODEL_REV` and `JINA_CODE_REV`.
- **Offline by construction**: weights baked into the image, offline flags set in the image and in the child process.
- **`chunkSource` filters files itself** (found by a unit test) rather than trusting the collector.
- **`initializeSchema` tolerates the "equivalent index already exists" race** (found by running test files in parallel).
- **Embedder timeout is configurable** (`EMBED_TIMEOUT_MS`, default 120 minutes); the original 30 minutes aborted a real repo run.
- **No opt-in flag on `ingest`**; `chunk-embed` is a separate command so the structural path and its output are unchanged.
- **Not added to `graph_query`**: needs its own latency and security design.
- **Token cap is part of the semantic config** (`maxEmbedTokens`, default 8192 = model maximum; `EMBED_MAX_TOKENS` lowers it). It joins the config hash only when below the default so existing snapshots stay valid. Per-chunk `tokenTruncated` and `embeddedTokens` are stored, and the snapshot stores `semanticMaxEmbedTokens` and `semanticTokenTruncatedCount`. Reason: attention memory grows with the square of the token count; with a cap of 2048 the embedder peak was 1,849 MB on FastAPI.
- **An incomplete layer may restart under a new config** (its chunks are deleted and it begins again); a complete layer still refuses a different config. The handoff only required refusing complete snapshots.
- **Rows are saved while the model runs** (every 15 s) and **the embedder process is restarted every 100 chunks** (`EMBED_SEGMENT`), so a freeze loses seconds, not a repository, and process memory resets.
- **Model containers run with `--memory` equal to `--memory-swap`** (2.4 GB for the capped run) so an overrun kills the container instead of swapping the host. Neo4j already had a 1.5 GB limit.
- **Search falls back to an exact cosine scan over the snapshot's chunks** when the global index fetch of 600 is crowded out by other snapshots (`method: exact-scan`). Chosen over a larger over-fetch because it is exact and bounded by the 20000-chunk limit.
- **Live tests run one file at a time** (`--test-concurrency=1`) because the test Neo4j has one CPU.
