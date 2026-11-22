# Test Cases

- Graphify extraction returns a valid snapshot for a fixture repo.
- Snapshot validation rejects malformed input.
- Snapshot validation rejects oversize input.
- Neo4j schema initialization is idempotent.
- Loading the same snapshot twice is safe.
- Retrieval is scoped by repo and version.
- Query results match expected graph entities/relationships.
