# Benchmarks: semantic code chunks

Only fixtures and public repositories are used. Where something was not measured, it says so.

## Fixture (3 Python files, real model)

3 chunks, 11 links, model load 4.3 s, embedding 6.6 s, peak RSS 1247 MB, on a 2-core / 4-thread test laptop. Repeat `chunk-embed`: `unchanged` in 4 s with no model load.

Search, top 3 of 3: on-topic queries scored 0.879, 0.820 and 0.881 with the right file first; the off-topic query topped out at 0.627.

## Public repositories (2026-11-14)

Embedded with `jinaai/jina-embeddings-v2-base-code` at the pinned revision, `EMBED_MAX_TOKENS=2048`, `TORCH_THREADS=2`, in a container limited to 2 CPUs and 3 GB with swap off, on a laptop with an Intel Core i3-1000NG4 (2 cores / 4 threads, 16 GB RAM). Figures are the embedder's own report.

| Repository | Commit | Chunks | Cut by the token cap | Links | Model load | Embedding time | Per chunk | Embedder peak RSS | State |
|---|---|---|---|---|---|---|---|---|---|
| FastAPI | `913c68062c89` | 1,638 | 1 | 7,184 | 10.2 s | 4,270 s (71 min) | 2.6 s | 1,849 MB | `ready` |
| NestJS | `2731c18054fb` | 2,600 | 0 | 9,581 | 15.4 s | 5,218 s (87 min) | 2.0 s | 1,606 MB | `ready` |

Neither run came near the 3 GB limit.

`semantic_search` over FastAPI served the public eval (1,080 runs, 0 errors).

## Memory

The embedder's memory grows quickly with a chunk's token count (attention), so the longest chunks decide the peak. That is why `EMBED_MAX_TOKENS` exists and why model containers should run with a memory limit and swap off. The 2048-token cap used here is a default choice, not a measured optimum.

## Not measured (do not infer)

- Recall or precision against labelled queries.
- Anything near the 20,000-chunk bound.
- A different CPU architecture, or GPU.
- Concurrent searches under load.

## How to reproduce

1. Build the image: `docker build -f Dockerfile.base -t taffee-base:dev .`
2. Ingest the repository (001), then run `npm run context -- chunk-embed <repoId> <repoPath> <sha>` in a container with `--memory 3g --memory-swap 3g` and `EMBED_MAX_TOKENS=2048`, and record the embedder's own report (load seconds, embed seconds, peak RSS).
