# Structural graph data model

An immutable snapshot is identified by `(repoId, full commit SHA)`. The source checkout path is metadata and is excluded from the canonical graph hash. Each snapshot records commit time, Graphify version, extraction mode, raw artifact SHA-256, canonical content hash, counts, ingestion time, and a `ready` flag. Readers see only ready snapshots.

`ContextRepository` owns `ContextSnapshot` nodes. A snapshot owns `ContextEntity` nodes. Directed `RELATES` relationships connect entities only within the same snapshot. Original Graphify node and link properties are retained as JSON strings, while selected fields (`label`, `kind`, `community`, `relation`, `confidence`, `context`, source evidence, native order) are available as Neo4j properties. Duplicate native links are retained.

The loader rejects a second payload with different content for an existing identity. The write and ready transition occur in one transaction. Latest resolution chooses the greatest commit timestamp, breaking ties by SHA; it is a mutable lookup, while explicit commit queries are stable.

## Semantic layer

`(ContextSnapshot)-[:HAS_CHUNK]->(ContextChunk)-[:DESCRIBES]->(ContextEntity)`. A `ContextChunk` is a fixed 150-line window of one source file at the snapshot's exact commit, identified by `(snapshotId, id)` with `id = <snapshotId>::chunk::<file>::<startLine>`. It stores `file`, `startLine`, `endLine`, `charCount`, `embeddedChars`, `truncated` (text over 8000 characters is cut before embedding) and a 768-dimension `embedding` with a cosine vector index (`context_chunk_embedding`). Chunk text is not stored. A chunk `DESCRIBES` an entity when the entity's `sourceFile` equals the chunk file and its start line (`L<n>`) falls inside the chunk's range; there is no name matching.

The snapshot carries separate semantic state: `semanticStatus` (`building` or `ready`), the model, model and remote-code revisions, dimension, chunk size, character cap, extensions, chunk, truncated and link counts, a config hash and a content hash (config, chunk layout and links; vectors excluded). Search reads only snapshots whose `semanticStatus` is `ready`. A snapshot with a complete semantic layer refuses a different model or chunking configuration. The structural `ready` flag, hash and immutability are unchanged.
