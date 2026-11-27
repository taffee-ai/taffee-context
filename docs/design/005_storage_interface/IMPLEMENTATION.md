# 005 Storage interface: implementation status

Status: implemented and verified on the test host. See VERIFICATION.md for the evidence.

| Step | Work | Status |
|---|---|---|
| 1 | Golden set captured: 13 MCP outputs, byte-stable across two runs | done |
| 2 | Requirements, design, decisions, test plan | done |
| 3 | Read methods in `contract.py` (`ReadStore`) and their Neo4j implementation in `neo4j_store.py` | done |
| 4 | Read-only view `read_view.py` (`ReadOnlyView`) and `open_read_store()` in `storage/__init__.py` | done |
| 5 | Provider tests `python/tests/test_read_store.py` (read path, view, id format) | done: 31 of 31 Python tests pass with the database tests enabled |
| 6 | MCP tools switched to the view: `server.py` uses `store.*` for every read; the `run()` helper is removed; the pack keeps its driver (phase 2) | done |
| 7 | Parity (13 of 13 byte-identical), kill and restart twice | done: cycles 1 and 2 both 13 of 13 |
| 8 | Existing suites: TypeScript 41 of 41; Python 31 of 31 | done |

## Source of each read (copied verbatim into the store)

| Store method | Replaces in | Lines in server.py at the start of step 3 |
|---|---|---|
| `list_repos_page` | `list_repos` | 239-260 |
| `resolve_snapshot` | `snapshot()` | 73-86 |
| `stats` | `graph_stats` | 261-273 |
| `find_nodes` | `find_node()` | 89-102 |
| `neighbours` | `neighbours()` | 112-117 |
| `read_graph` | `build_graph()` | 147-166 |
| `community_members` | `get_community` | 356-367 |
| `shortest_path` | `shortest_path` | 369-388 |
| `semantic_state` | `semantic_search` state check | 440-451 |
| `scoped_chunks` | `_scoped_chunks()` | 423-439 |
| `global_chunks` | `semantic_search` global branch | 455-462 |
| `chunk_symbols` | `semantic_search` symbols | 463-468 |
| `file_has_entities` | `read_code` existence check | 497 |

The line numbers are approximate: they were read from the file before the change.

## Defects found while implementing (fixed, with tests)

1. **Snapshot ID format.** The Python write path used `repo@sha`. The TypeScript loader and the MCP server use JSON `["repo","sha"]`. Fixed: `snapshot_id()` produces the JSON form. Test: `test_snapshot_id_matches_the_typescript_loader`.
2. **Community type.** The TypeScript loader stores community as text. The Python contract had an integer. Fixed: text in the contract and in the store.
3. **Staged data was readable through the snapshot-scoped reads.** Each snapshot-scoped read now checks readiness first and raises the same "no ready snapshot" message as the resolver. Test: `test_staged_snapshot_is_invisible`.

## Open items

- **Neo4j read-only database user (D-005-4).** Not implemented. The MCP service still connects with the Neo4j admin user, so the read-only rule is enforced by the code path only. Required before production.
- **Phase 2: the context pack.** `turbo_data.py` still runs its own Cypher through the server's driver. Its methods (candidates, expansion, dependency chain) move to the read contract next.
- **Semantic-layer writes in Python.** Still in TypeScript.
- **Readiness check cost.** Each snapshot-scoped read runs one extra indexed lookup. Not measured on large repos.
