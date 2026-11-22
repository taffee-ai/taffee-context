# Requirements

- Ingest a local source checkout at an exact commit.
- Run Graphify-based code extraction.
- Produce a bounded graph snapshot artifact.
- Validate snapshot structure before loading.
- Load snapshots into Neo4j idempotently and safely.
- Query graph data by repository and version.
- Keep Neo4j runtime setup outside application code under `infra/neo4j`.
- Provide context-specific tests and verification evidence.
