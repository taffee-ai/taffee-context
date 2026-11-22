import neo4j from 'neo4j-driver';
import type { Neo4jConnection } from '../../storage/neo4j/client.ts';
import { commitSHA, requiredText } from '../../types.ts';

export interface GraphQuery {
  repoId: string;
  commitSHA?: string;
  operation: 'resolve' | 'find_symbol' | 'get_callers' | 'get_callees' | 'get_dependencies';
  symbol?: string;
  limit?: number;
}
export function validateQuery(args: Record<string, unknown>): GraphQuery {
  const allowed = ['repoId', 'commitSHA', 'operation', 'symbol', 'limit'];
  if (Object.keys(args).some(k => !allowed.includes(k))) throw new Error('Unknown graph query argument');
  const repoId = requiredText(args.repoId, 'repoId', 256);
  const operation = requiredText(args.operation, 'operation') as GraphQuery['operation'];
  if (!['resolve', 'find_symbol', 'get_callers', 'get_callees', 'get_dependencies'].includes(operation)) throw new Error('Unsupported graph operation');
  const limit = args.limit ?? 10;
  if (typeof limit !== 'number' || !Number.isInteger(limit) || limit < 1 || limit > 20) throw new Error('limit must be an integer from 1 to 20');
  return { repoId, operation, limit,
    ...(args.commitSHA === undefined ? {} : { commitSHA: commitSHA(args.commitSHA) }),
    ...(operation === 'resolve' ? {} : { symbol: requiredText(args.symbol, 'symbol') }),
  };
}
export async function queryGraph(connection: Neo4jConnection, input: GraphQuery, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const query = validateQuery(input as unknown as Record<string, unknown>);
  signal?.throwIfAborted();
  const session = connection.driver.session({ database: connection.database, defaultAccessMode: neo4j.session.READ });
  const abort = () => { void session.close().catch(() => {}); };
  signal?.addEventListener('abort', abort, { once: true });
  try {
    return await session.executeRead(async tx => {
      signal?.throwIfAborted();
      const result = await tx.run(`MATCH (s:ContextSnapshot {repoId: $repoId, ready: true})
        WHERE $sha IS NULL OR s.commitSHA = $sha
        RETURN s { .id, .repoId, .commitSHA, .commitTimestamp, .graphifyVersion, .ingestionTimestamp } AS snapshot
        ORDER BY s.commitTimestamp DESC, s.commitSHA DESC LIMIT 1`, { repoId: query.repoId, sha: query.commitSHA ?? null });
      if (!result.records.length) return { snapshot: null, results: [] };
      const snapshot = result.records[0].get('snapshot');
      if (query.operation === 'resolve') return { snapshot, results: [] };
      const params: Record<string, unknown> = { id: snapshot.id, symbol: query.symbol, limit: neo4j.int(query.limit! + 1) };
      let statement: string;
      if (query.operation === 'find_symbol') {
        statement = `MATCH (n:ContextEntity {snapshotId: $id})
          WHERE n.localId = $symbol OR toLower(n.label) CONTAINS toLower($symbol)
          RETURN n { .localId, .label, .kind, .sourceFile, .sourceLocation, .community, .nativeOrder } AS item
          ORDER BY n.localId LIMIT $limit`;
      } else {
        // Exact localId eliminates ambiguous same-named symbol traversal.
        const incoming = query.operation === 'get_callers';
        params['relations'] = query.operation === 'get_dependencies'
          ? ['imports', 'imports_from', 'uses', 'depends_on', 'requires'] : ['calls'];
        statement = `MATCH (n:ContextEntity {snapshotId: $id, localId: $symbol})
          MATCH ${incoming ? '(m:ContextEntity)-[r:RELATES]->(n)' : '(n)-[r:RELATES]->(m:ContextEntity)'}
          WHERE m.snapshotId = $id AND toLower(r.relation) IN $relations
          RETURN {entity: m { .localId, .label, .kind, .sourceFile, .sourceLocation, .community, .nativeOrder },
            relation: r.relation, confidence: r.confidence, context: r.context,
            sourceFile: r.sourceFile, sourceLocation: r.sourceLocation, nativeOrder: r.nativeOrder} AS item
          ORDER BY m.localId, r.relation LIMIT $limit`;
      }
      const rows = await tx.run(statement, params);
      signal?.throwIfAborted();
      return { snapshot, results: rows.records.slice(0, query.limit).map(row => row.get('item')),
        limit: query.limit, truncated: rows.records.length > query.limit! };
    }, { timeout: 3000 });
  } finally {
    signal?.removeEventListener('abort', abort);
    await session.close();
  }
}
