# Verification

Status: structural code-ingestion slice implemented in `context/` and verified on the designated Ubuntu host on 2026-10-06. Full evidence is in `docs/design/verification.md`.

- Commands run: typecheck, `npm test` (41 of 41 with live Neo4j and Graphify, 2026-11-22), operator CLI `init-schema | ingest | verify | query` on a fixture repo; FastAPI and NestJS (public) ingested to `ready` on 2026-11-14.
- Environment: `Dockerfile.base` (Node 20.20.2, Python 3.12.15, graphifyy 0.9.51), Neo4j 5.26.0-community, all in containers.
- Results: no type errors; all live tests pass; ingest created then reported `unchanged` on repeat; `verify` passed on the fixture.
- Known gaps: `verify` does not detect a node-property edit that keeps counts unchanged; submodule refusal and the 32 MiB bound untested; external baseline comparison not yet run; semantic chunks and embeddings out of scope.
