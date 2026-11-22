import { connectNeo4j } from '../../storage/neo4j/client.ts';
import { queryGraph, validateQuery } from './neo4j-query.ts';
const MAX_OUTPUT_BYTES = 64 * 1024;

export async function graphQueryTool(args: Record<string, unknown>, context?: { signal?: AbortSignal }): Promise<string> {
  const query = validateQuery(args);
  // Repository scope is an operator setting, not model-supplied authorization.
  const allowed: unknown = JSON.parse(process.env.TAFFEE_CONTEXT_REPOS ?? '[]');
  if (!Array.isArray(allowed) || !allowed.every(x => typeof x === 'string') || !allowed.includes(query.repoId)) {
    throw new Error('Repository is not enabled for context queries');
  }
  const connection = connectNeo4j();
  try {
    const response = await queryGraph(connection, query, context?.signal);
    const results = response.results as unknown[];
    // Preserve valid JSON through the output bound; never slice JSON.
    while (Buffer.byteLength(JSON.stringify(response), 'utf8') > MAX_OUTPUT_BYTES && results.length) {
      results.pop(); response.truncated = true;
    }
    if (Buffer.byteLength(JSON.stringify(response), 'utf8') > MAX_OUTPUT_BYTES) throw new Error('Context query metadata exceeds output bound');
    return JSON.stringify(response);
  }
  catch (error) { throw new Error('Context query failed; check database connectivity and operator configuration', { cause: error }); }
  finally { await connection.close(); }
}
export const GRAPH_QUERY_SCHEMA = {
  type: 'function', function: {
    name: 'graph_query',
    description: 'Read an enabled repository code graph. Resolve exact commit or latest available; find symbols, then use returned localId for callers/callees/dependencies. No raw Cypher.',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        repoId: { type: 'string' }, commitSHA: { type: 'string', description: 'Full Git SHA. Omit for newest ingested commit timestamp.' },
        operation: { type: 'string', enum: ['resolve', 'find_symbol', 'get_callers', 'get_callees', 'get_dependencies'] },
        symbol: { type: 'string', description: 'Label fragment for find_symbol; exact localId for relationship queries.' },
        limit: { type: 'integer', minimum: 1, maximum: 20 },
      }, required: ['repoId', 'operation'],
    },
  },
};
