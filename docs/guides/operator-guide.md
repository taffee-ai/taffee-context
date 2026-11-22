# Operator guide

Run these commands on the designated execution host described by the local build and test policy. Node 20+, Python 3.10+ and Docker Compose are required. Use a dedicated Python environment for the pinned Graphify package.

```sh
npm install
python3 -m venv .venv
.venv/bin/pip install -r context/ingestion/extract/code/requirements.txt
export GRAPHIFY_PYTHON="$PWD/.venv/bin/python"
export GRAPHIFY_BIN="$PWD/.venv/bin/graphify"
export NEO4J_PASSWORD='<choose-a-password>'
export NEO4J_URI='bolt://127.0.0.1:17687'
# The stack definition lives in the taffee-core umbrella repository (infra/compose.yaml), beside this one
docker compose -f ../taffee-core/infra/compose.yaml up -d graphdb
npm run context -- init-schema
```

For a local Git repository, obtain the exact full SHA with `git -C <repo> rev-parse HEAD`. Use an output path outside the repository or a path ending in `.snapshot.json`, which Git ignores at `context/` level. A snapshot file contains source code metadata and should be handled as sensitive data.

```sh
npm run context -- ingest my-repo /path/to/repo <full-sha> context/my-repo.snapshot.json
npm run context -- verify my-repo <full-sha> context/my-repo.snapshot.json
npm run context -- query my-repo resolve
npm run context -- query my-repo find_symbol caller <full-sha> 10
npm run context -- query my-repo get_callees <localId> <full-sha>
```

`extract` writes a snapshot file without accessing Neo4j; `load` imports an existing snapshot. `ingest` extracts, saves, and loads. Pass `-` as the output path to avoid saving a snapshot file. `verify` compares the saved snapshot's content hash, raw artifact hash, and entity/relationship counts with Neo4j. `query` uses a repository ID and optional exact commit; omitted commit means latest ingested commit time. Query outputs are structural evidence, not permission-filtered context packs. Restrict database and CLI access to trusted operators.

For automated checks, run `npm run typecheck` and `npm test`. Set `TAFFEE_NEO4J_TEST=1` to enable live database and Graphify tests. `TAFFEE_CONTEXT_REPOS` is an optional JSON allowlist for the separate `graphQueryTool` wrapper; the operator CLI is controlled by host/database access.

## Semantic layer (chunks, embeddings, search)

Requires a ready structural snapshot (`ingest` or `load`) and the embedding runtime. The embedding model runs locally in the same container as the CLI: build the image with `docker build -f Dockerfile.base -t taffee-base:dev .` (Node 20, Python 3.12, Graphify 0.9.51, torch CPU 2.8.0, transformers 4.57.1, and the pinned model and remote code baked in). Runs are offline (`HF_HUB_OFFLINE=1`); no hosted API or key is used.

```sh
npm run context -- chunk-embed my-repo /path/to/repo <full-sha>
npm run context -- search my-repo "where are failed payments retried" - 5
```

`chunk-embed` is idempotent: a complete layer reports `unchanged` without loading the model, and an interrupted run resumes by embedding only chunks that have no vector. It refuses a different configuration for a complete snapshot, and a second builder while one holds the snapshot's lease. `EMBED_TIMEOUT_MS` overrides the 2-hour embedder timeout; `TORCH_THREADS` (default 2) sets CPU threads. Load only one model-loading process at a time on a small host: the model needs about 1.2 GB resident and runs at 2.0 to 2.6 seconds per chunk on 2 threads for NestJS and FastAPI.

`search <repoId> <query> [sha|-] [topK]` embeds the query with the same model and returns file, line range, score, a truncation flag and up to 10 contained entities, plus `fetched`, `matched`, `filteredOut` and `possiblyIncomplete`. Omitting the commit means the latest commit whose semantic layer is ready. Results are structural and semantic evidence, not permission-filtered context.

Memory and the token cap: run the model container with `--memory` equal to `--memory-swap` so an overrun kills the container instead of swapping the host. The model needs about 1.0 GB resident for typical chunks, but attention memory grows with the square of a chunk's token count. `EMBED_MAX_TOKENS` (128 to 8192, default 8192) caps tokens per chunk; at 2048 the embedder peak was 1,849 MB on FastAPI. The cap is stored in the snapshot's semantic config and each cut chunk is flagged `tokenTruncated` (also shown in search results), and `search` reports `method` (`index` or `exact-scan`). An incomplete semantic layer restarts if you change the config; a complete layer refuses it. `EMBED_SEGMENT` (default 100) sets how many chunks one embedder process handles.
