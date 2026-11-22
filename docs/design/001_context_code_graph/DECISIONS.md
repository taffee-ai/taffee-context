# Decisions

| ID | Decision | Reason |
|---|---|---|
| 001 | Start with code graph context | Working implementation already exists in the workbench |
| 002 | Preserve the current ingestion/storage/retrieval shape | It matches the code and avoids taxonomy churn |
| 003 | Keep Neo4j infra at root `infra/neo4j` | Infra is runtime setup, not Context application code |
| 004 | Do not move MCP server in the first pass | MCP is a serving/capability surface and needs its own boundary decision |
| 005 | Do not move the full harness | The harness is an execution loop, not Context |
| 006 | Extract code only (`graphify extract --code-only`: tree-sitter, no LLM). Docs, images and video in repos are not extracted in the core pipeline | Cost: LLM extraction of unstructured and binary content grows with every repo and would be expensive at very large repo counts. It is better done by models built for it. Code-only also keeps the graph reproducible (same commit, same hash, so `verify` works), free per repo, and local. If added later it is an optional layer: the operator chooses the model (any OpenAI-compatible URL, local or hosted), results are cached by file content, folders are opt-in, spend is capped, and results are stored apart from the verified code graph (roadmap C17) |
