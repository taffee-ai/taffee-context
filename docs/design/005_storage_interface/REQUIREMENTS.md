# 005 Storage interface: requirements

Status: accepted for implementation. Baseline evidence: a golden set of 13 MCP outputs, byte-stable across two runs.

## Goal

Agents reach the code graph only through the MCP server. The MCP server must not depend on which graph database is used. A new database is added by writing one provider, not by changing the MCP tools or the ingestion code.

## Requirements

- **R1 Selectable provider.** The database is chosen by name (`GRAPH_DB_PROVIDER`). Unknown names are refused with the list of supported providers. Neo4j is the only provider today.
- **R2 No database names outside providers.** Outside `context/storage/`, no code imports a database driver or contains a database query.
- **R3 Read-only for the MCP server.** The MCP server receives a read view: an object that exposes read operations only. Write operations are not reachable from it. Each provider also documents a read-only database user; that user is required before production use (see DECISIONS D-005-4).
- **R4 Snapshot scoping.** Every read names one snapshot. Snapshot resolution keeps today's rules: newest ready snapshot by commit timestamp (ties broken by SHA); a commit prefix must match exactly one ready snapshot; no match and multiple matches are errors with today's messages.
- **R5 Staged data is invisible.** Reads return only ready snapshots.
- **R6 Behaviour parity.** The twelve MCP tools and the pack return the same JSON for the same inputs as before the change. Acceptance is byte equality on the golden set.
- **R7 Provider contract.** Every provider passes the same contract test suite. A provider is not supported until it does.
- **R8 Tool interface unchanged.** Tool names, parameters, output format, rate limits, authentication and error text are unchanged.

## Non-goals (this change)

- Writes from the MCP server (none exist, none will).
- Moving the TypeScript ingestion code to Python (separate migration, see 006).
- The context pack's database reads. They move in phase 2, with their own requirements, after phase 1 passes parity.
- Semantic-layer writes in Python (chunks, vectors, links). Separate phase.

## Evidence required to close

- Golden parity: all 13 captured outputs byte-equal after the change.
- Provider contract suite passes for Neo4j.
- Read view refuses writes (test).
- Stack kill and restart test passes after the change.
