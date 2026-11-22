# Benchmarks: structural code graph

Only fixtures and public repositories are used. Where something was not measured, it says so.

## Method

- Everything runs in containers: `Dockerfile.base` (Node 20.20.2, Python 3.12.15, graphifyy 0.9.51) and Neo4j 5.26.0-community.
- Extraction mode: `graphify extract --code-only --no-viz` (tree-sitter structure, no LLM, no chunks, no embeddings).
- Test machines are laptops, so absolute times are not production figures.

## Ingest results

| Repository | Commit | Files | Nodes | Edges | Ingest time | State |
|---|---|---|---|---|---|---|
| 3-function fixture | local | 1 | 4 | 5 | – | `ready`; repeat ingest `unchanged` |
| FastAPI (MIT) | `913c68062c89` | 3,244 | 9,342 | 18,919 | 59.2 s | `ready` |
| NestJS (MIT) | `2731c18054fb` | 2,519 | 15,185 | 36,714 | 88.4 s | `ready` |

The two public repositories were ingested on 2026-11-14 for the public eval (`eval/`), on a laptop with an Intel Core i3-1000NG4 (2 cores / 4 threads, 16 GB RAM), in a container limited to 2 CPUs and 2.5 GB. Ingest time is the wall time of `npm run context -- ingest` (Graphify extraction, validation and loading into Neo4j).

## Query behaviour

- On the fixture, `get_callees(caller)` returns `callee` and `get_callers(callee)` returns `caller`, matching the snapshot's edge direction.
- On FastAPI, the public eval found that calls made from inside nested functions are not recorded as caller edges (`eval/results/2026-11-14-fastapi/REPORT.md`).

## Not measured (do not infer)

- Peak memory of ingest (collected from the next run on; see `eval/DESIGN.md` section 6.5).
- Comparison against an external baseline (for example counts from another extractor).
- Behaviour near the 50,000 node / 200,000 edge bounds (NestJS is the largest so far).
- Concurrent load beyond the live test that races two ingests of one repository.
- Neo4j query latency for `find_symbol`, `get_callers`, `get_callees` and `get_dependencies`.

## How to reproduce

1. Build the image: `docker build -f Dockerfile.base -t taffee-base:dev .`
2. Start Neo4j from `infra/neo4j/compose.yaml` in the `taffee-core` umbrella repository.
3. Clone a repository at the commit in `eval/repos.yaml`, then run `npm run context -- ingest <repoId> <repoPath> <sha> -` and record the wall time; run it again and expect `unchanged`.
