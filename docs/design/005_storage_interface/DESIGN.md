# 005 Storage interface: design

## Layers

    MCP tools (server.py)            unchanged signatures, rate limit, auth, output format
          |  ReadStore (read-only view)
    taffee_context/storage/read_view.py   the only object the MCP server holds for data
          |  GraphStore read methods
    taffee_context/storage/<provider>  Neo4j today; other providers later
          |  driver
    database

Ingestion (TypeScript, unchanged in this change) writes through its own Neo4j code. Its migration to the Python write contract is a separate step.

## Contract

Python `Protocol`s in `taffee_context/storage/contract.py`.

Write side (exists, tested): `initialize`, `stage_snapshot`, `publish_snapshot`, `summary`, `close`.

Read side (this change). Each method is scoped to one snapshot (a `SnapshotRef`) unless it lists repos.

| Method | Replaces (server.py / turbo_data.py) | Returns |
|---|---|---|
| `list_repos(query, limit, offset, all_commits)` | `list_repos` | page of repo rows: repo, commit, committed, entities, edges, semantic, chunks, commits_available |
| `resolve_snapshot(repo, commit_prefix)` | `snapshot()` | SnapshotRef; raises `NotFound` or `Ambiguous` with today's messages |
| `graph_stats(ref)` | `graph_stats` | nodes, communities, edges, edge confidence counts, chunks |
| `find_nodes(ref, label)` | `find_node()` | up to five rows: id, label, file, loc, kind. Tiers: exact label or id, then suffix, then substring |
| `neighbours(ref, node_id, relation, limit)` | `neighbours()` | rows: rel, outgoing, conf, id, label, file, loc |
| `read_graph(ref)` | `build_graph()` | node rows (order, native properties, id) and edge rows (order, native properties), sorted as today |
| `community_members(ref, community_id, limit)` | `get_community` | rows: label, file, loc, id |
| `path_endpoints(ref, source, target)` | `shortest_path` endpoint query | the two nodes, or none |
| `semantic_state(ref)` | `semantic_search` state check | semantic status string |
| `vector_search(ref, vector, fetch)` | `_scoped_chunks`, `semantic_search` | chunk rows with score |
| `chunk_symbols(ref, chunk_id)` | `semantic_search` symbols | entity rows linked by DESCRIBES |
| `file_has_entities(ref, file)` | `read_code` existence check | bool |

Exact Cypher is copied from the current files, so behaviour is the same. The copies are referenced by line in IMPLEMENTATION.md.

## Read view

`ReadStore` is a Protocol with only the read methods above plus `close`. `ReadOnlyView(store)` wraps a provider and exposes only those methods, so a caller cannot reach `stage_snapshot`, `publish_snapshot`, or the raw driver. The MCP server obtains its store with `open_read_store()` (in `taffee_context/storage/__init__.py`), which reads `GRAPH_DB_PROVIDER` and returns a view.

## Errors

`NotFound`, `Ambiguous`, `InvalidInput`. The MCP layer converts them to the same `ValueError` messages as today, so tool output text is unchanged.

## Graphify

`build_graph` and the graph helpers keep running Graphify's own code on an in-memory graph. Only the data source changes: `read_graph(ref)` replaces the Cypher.

## Configuration

`GRAPH_DB_PROVIDER` (default `neo4j`), plus the provider's own variables (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`). `QUERY_TIMEOUT_SECONDS` keeps its meaning for reads.

## Phase 2 (not in this change)

The context pack (`turbo_data.py`: candidates, expansion, dependency chain) moves to the read contract after phase 1 passes parity. Its methods are listed in IMPLEMENTATION.md as deferred.
