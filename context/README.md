# Code context ingestion

This first TAFFEE context slice turns one local Git repository at an exact commit into a validated structural graph in Neo4j. Graphify extracts code entities and relationships; TAFFEE checks identity, provenance, paths, graph integrity, and snapshot immutability before making the graph queryable.

The supported input is an existing local repository plus a full commit SHA. The working tree is never ingested: TAFFEE creates a temporary checkout of the requested commit. Symlinks and submodules are refused. The source repository is read-only.

An optional semantic layer splits the same exact-commit source into 150-line chunks, embeds them with a pinned local model (`jinaai/jina-embeddings-v2-base-code`, run offline in a container), stores the vectors in a Neo4j vector index, links each chunk to the entities it contains, and adds a scoped `search` command. It is built by a separate `chunk-embed` command and never changes the structural snapshot. Implemented and run on the execution host; see verification for results and gaps.

A read-only MCP server over the same graph and chunks lives in [serving/mcp](serving/mcp/README.md): 12 tools (graph queries, impact analysis, semantic search, committed-code reads) with token authentication, rate limiting and sanitized errors. Implemented and tested on the execution host; see verification.

See [operator guide](../docs/guides/operator-guide.md) for installation and commands, [data model](../docs/guides/data-model.md) for graph semantics, and [verification](../docs/design/verification.md) for evidence from the first remote run.

The same ingestion steps run as a service with a job queue. See the [repository README](../README.md#ingestion-service).
