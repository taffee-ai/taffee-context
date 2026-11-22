import type { Neo4jConnection } from '../../storage/neo4j/client.ts';
import { snapshotId, type RepositorySnapshot } from '../../types.ts';
import { graphHash } from './validate-snapshot.ts';

export interface VerifyOptions {
  /** true (default) requires the snapshot to be published; false checks a staged snapshot. */
  requireReady?: boolean;
}

export async function verifyStoredSnapshot(connection: Neo4jConnection, snapshot: RepositorySnapshot, options: VerifyOptions = {}) {
  const expected = graphHash(snapshot);
  const match = (options.requireReady ?? true) ? '{id: $id, ready: true}' : '{id: $id}';
  const session = connection.driver.session({ database: connection.database });
  try {
    const rows = await session.run(`MATCH (s:ContextSnapshot ${match})
      OPTIONAL MATCH (s)-[:HAS_ENTITY]->(n:ContextEntity)
      WITH s, count(n) AS nodes
      OPTIONAL MATCH (a:ContextEntity {snapshotId: $id})-[e:RELATES]->(b:ContextEntity {snapshotId: $id})
      RETURN s.contentHash AS hash, s.artifactHash AS artifactHash, s.nodeCount AS declaredNodes,
        s.edgeCount AS declaredEdges, nodes, count(e) AS edges`, { id: snapshotId(snapshot.repoId, snapshot.commitSHA) });
    if (!rows.records.length) throw new Error('Snapshot missing');
    const row = rows.records[0];
    const counts = { nodes: Number(row.get('nodes')), edges: Number(row.get('edges')) };
    if (row.get('hash') !== expected || row.get('artifactHash') !== snapshot.artifactHash ||
        counts.nodes !== snapshot.nodes.length || counts.edges !== snapshot.edges.length ||
        Number(row.get('declaredNodes')) !== counts.nodes || Number(row.get('declaredEdges')) !== counts.edges) {
      throw new Error('Stored snapshot does not match the source artifact');
    }
    return { id: snapshotId(snapshot.repoId, snapshot.commitSHA), graphHash: expected, artifactHash: snapshot.artifactHash, ...counts };
  } finally { await session.close(); }
}
