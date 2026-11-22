import type { Neo4jConnection } from '../../storage/neo4j/client.ts';
import { snapshotId, type RepositorySnapshot } from '../../types.ts';
import { graphHash, validateSnapshot } from './validate-snapshot.ts';

export interface LoadSnapshotOptions {
  timeoutMs?: number;
  /** false loads the structure as staged: invisible to readers until publishSnapshot. Default true. */
  publish?: boolean;
}

export async function loadSnapshot(
  connection: Neo4jConnection,
  input: RepositorySnapshot,
  options: LoadSnapshotOptions = {},
): Promise<{ id: string; status: 'created' | 'unchanged' }> {
  const snapshot = validateSnapshot(input);
  const id = snapshotId(snapshot.repoId, snapshot.commitSHA);
  const hash = graphHash(snapshot);
  const totalElements = snapshot.nodes.length + snapshot.edges.length;
  const calculatedTimeout = Math.max(60_000, 30_000 + Math.ceil(totalElements / 500) * 5_000);
  const envTimeout = process.env.INGESTION_TX_TIMEOUT_MS ? parseInt(process.env.INGESTION_TX_TIMEOUT_MS, 10) : undefined;
  const timeout = options.timeoutMs ?? (envTimeout && !isNaN(envTimeout) ? envTimeout : calculatedTimeout);
  const publish = options.publish ?? true;
  const session = connection.driver.session({ database: connection.database });
  try {
    return await session.executeWrite(async tx => {
      // MERGE + dependent property update obtains a repository write lock.
      // Concurrent workers for this repo serialize before inspecting the snapshot.
      await tx.run(`MERGE (r:ContextRepository {repoId: $repoId})
        SET r.writeSequence = coalesce(r.writeSequence, 0) + 1`, { repoId: snapshot.repoId });
      const existing = await tx.run('MATCH (s:ContextSnapshot {id: $id}) RETURN s.contentHash AS hash', { id });
      if (existing.records.length) {
        if (existing.records[0].get('hash') !== hash) throw new Error('Immutable snapshot conflict: graph content or extractor version differs');
        return { id, status: 'unchanged' as const };
      }
      const { nodes, edges, ...metadata } = snapshot;
      await tx.run(`MATCH (r:ContextRepository {repoId: $repoId})
        CREATE (s:ContextSnapshot $metadata) CREATE (r)-[:HAS_SNAPSHOT]->(s)`, {
        repoId: snapshot.repoId, metadata: { ...metadata, id, contentHash: hash,
          ingestionTimestamp: new Date().toISOString(), schemaVersion: 1, nodeCount: nodes.length, edgeCount: edges.length },
      });
      for (let i = 0; i < nodes.length; i += 500) {
        await tx.run(`MATCH (s:ContextSnapshot {id: $id}) UNWIND $nodes AS n
          CREATE (e:ContextEntity {snapshotId: $id, localId: n.id,
            label: n.label, kind: n.kind, sourceFile: n.sourceFile, sourceLocation: n.sourceLocation,
            community: n.community, nativeOrder: n.nativeOrder, nativePropertiesJson: n.nativePropertiesJson})
          CREATE (s)-[:HAS_ENTITY]->(e)`, { id, nodes: nodes.slice(i, i + 500) });
      }
      for (let i = 0; i < edges.length; i += 500) {
        await tx.run(`UNWIND $edges AS e
          MATCH (a:ContextEntity {snapshotId: $id, localId: e.source})
          MATCH (b:ContextEntity {snapshotId: $id, localId: e.target})
          CREATE (a)-[:RELATES {relation: e.relation, confidence: e.confidence,
            sourceFile: e.sourceFile, sourceLocation: e.sourceLocation,
            context: e.context, nativeOrder: e.nativeOrder, nativePropertiesJson: e.nativePropertiesJson}]->(b)`, { id, edges: edges.slice(i, i + 500) });
      }
      // Readers see this flag and the graph together at commit, never midway.
      await tx.run('MATCH (s:ContextSnapshot {id: $id}) SET s.ready = $ready, s.staged = $staged',
        { id, ready: publish, staged: !publish });
      return { id, status: 'created' as const };
    }, { timeout });
  } finally { await session.close(); }
}

/** Makes a staged snapshot visible to readers. Call only after its semantic layer is built and verified. */
export async function publishSnapshot(connection: Neo4jConnection, repoId: string, commitSHA: string): Promise<void> {
  const session = connection.driver.session({ database: connection.database });
  try {
    // Idempotent: a snapshot that is already ready stays ready.
    const result = await session.executeWrite(tx => tx.run(
      'MATCH (s:ContextSnapshot {id: $id}) SET s.ready = true, s.staged = false RETURN s.id AS id',
      { id: snapshotId(repoId, commitSHA) }));
    if (!result.records.length) throw new Error('Snapshot to publish does not exist');
  } finally { await session.close(); }
}
