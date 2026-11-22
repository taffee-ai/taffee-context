import type { Neo4jConnection } from './client.ts';

// Additive, idempotent migration 001. Future migrations append; never rewrite it.
export const SCHEMA_V1 = [
  'CREATE CONSTRAINT context_repository_id IF NOT EXISTS FOR (r:ContextRepository) REQUIRE r.repoId IS UNIQUE',
  'CREATE CONSTRAINT context_snapshot_id IF NOT EXISTS FOR (s:ContextSnapshot) REQUIRE s.id IS UNIQUE',
  'CREATE CONSTRAINT context_entity_id IF NOT EXISTS FOR (n:ContextEntity) REQUIRE (n.snapshotId, n.localId) IS UNIQUE',
  'CREATE INDEX context_snapshot_resolution IF NOT EXISTS FOR (s:ContextSnapshot) ON (s.repoId, s.commitTimestamp)',
];
// Additive migration 002: semantic code chunks. Index syntax targets Neo4j 5.26.
export const SCHEMA_V2 = [
  'CREATE CONSTRAINT context_chunk_id IF NOT EXISTS FOR (c:ContextChunk) REQUIRE (c.snapshotId, c.id) IS UNIQUE',
  `CREATE VECTOR INDEX context_chunk_embedding IF NOT EXISTS FOR (c:ContextChunk) ON (c.embedding)
    OPTIONS {indexConfig: {\`vector.dimensions\`: 768, \`vector.similarity_function\`: 'cosine'}}`,
];
export async function initializeSchema(connection: Neo4jConnection): Promise<void> {
  const session = connection.driver.session({ database: connection.database });
  try {
    for (const statement of [...SCHEMA_V1, ...SCHEMA_V2]) {
      // Concurrent initializers can race on IF NOT EXISTS; the equivalent schema rule existing is the desired end state.
      try { await session.run(statement); }
      catch (error) {
        if ((error as { code?: string }).code !== 'Neo.ClientError.Schema.EquivalentSchemaRuleAlreadyExists') throw error;
      }
    }
    await session.run('CALL db.awaitIndexes(30)');
  } finally { await session.close(); }
}
