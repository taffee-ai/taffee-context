# Requirements: semantic code chunks

Scope: code only, on top of an existing ready structural snapshot. No hosted model API, no API key, no network at run time.

1. Split the source of the exact commit into 150-line windows (`.ts .tsx .js .jsx .py`; skip whitespace-only windows, `.min.` files and `node_modules`).
2. Embed each window with the pinned local model `jinaai/jina-embeddings-v2-base-code` (768 dimensions) running on CPU inside a container. Text longer than 8000 characters is cut and flagged `truncated`.
3. Store vectors in Neo4j on `ContextChunk` nodes with a cosine vector index. Chunk text is not stored; code is read from Git when needed.
4. Link each chunk to the entities whose `sourceFile` equals the chunk file and whose start line falls inside the chunk's line range. No name matching.
5. Keep structural readiness and immutability unchanged. A separate `semanticStatus` (`building` or `ready`) gates search; an interrupted run never looks complete and can be resumed.
6. Refuse a different model, revision or chunking parameters for a snapshot that already has a semantic layer.
7. Search is scoped to one repository and one snapshot, reports how many rows were filtered out, and never returns another repository's or commit's chunks.
8. Bounds: at most 5000 files, 1 MiB per file, 20000 chunks, 256 MiB of embedding output, a run timeout. Symlinks and submodules are refused.
9. Out of scope: MCP/HTTP server, permissions, token budgeting, semantic search in the model-callable `graph_query` tool, non-code sources, hardening `verify`.
