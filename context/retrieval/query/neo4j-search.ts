import neo4j from 'neo4j-driver';
import type { Neo4jConnection } from '../../storage/neo4j/client.ts';
import { commitSHA, requiredText } from '../../types.ts';
import { SEMANTIC_CONFIG } from '../../ingestion/chunks/chunker.ts';
import { pythonEmbedder, validateEmbedding, type Embed } from '../../ingestion/embeddings/run-embedder.ts';

// The vector index is global across snapshots, so over-fetch and then keep only one ready snapshot's chunks.
export const SEARCH_FETCH = 600;

export interface SearchQuery { repoId: string; query: string; commitSHA?: string; topK: number }
export function validateSearch(args: Record<string, unknown>): SearchQuery {
  const allowed = ['repoId', 'query', 'commitSHA', 'topK'];
  if (Object.keys(args).some(k => !allowed.includes(k))) throw new Error('Unknown search argument');
  const topK = args.topK ?? 8;
  if (typeof topK !== 'number' || !Number.isInteger(topK) || topK < 1 || topK > 25) throw new Error('topK must be an integer from 1 to 25');
  return { repoId: requiredText(args.repoId, 'repoId', 256), query: requiredText(args.query, 'query', 1000), topK,
    ...(args.commitSHA === undefined ? {} : { commitSHA: commitSHA(args.commitSHA) }) };
}

/** Embeds the query with the same pinned model and settings as ingestion. */
export async function embedQuery(text: string, embed: Embed = pythonEmbedder()): Promise<number[]> {
  const rows: { id: string; embedding: number[] }[] = [];
  await embed([{ id: 'query', text: text.slice(0, SEMANTIC_CONFIG.maxEmbedChars) }], async batch => { rows.push(...batch); });
  if (rows.length !== 1) throw new Error('Query embedding missing');
  return validateEmbedding(rows[0], SEMANTIC_CONFIG.dimension).embedding;
}

export async function searchChunks(connection: Neo4jConnection, input: SearchQuery, embed: (text: string) => Promise<number[]> = embedQuery): Promise<Record<string, unknown>> {
  const query = validateSearch(input as unknown as Record<string, unknown>);
  const session = connection.driver.session({ database: connection.database, defaultAccessMode: neo4j.session.READ });
  try {
    const found = await session.run(`MATCH (s:ContextSnapshot {repoId: $repoId, ready: true})
      WHERE $sha IS NULL OR s.commitSHA = $sha
      RETURN s { .id, .commitSHA, .commitTimestamp, .semanticStatus, .semanticModel, .semanticModelRevision } AS snapshot
      ORDER BY coalesce(s.semanticStatus = 'ready', false) DESC, s.commitTimestamp DESC, s.commitSHA DESC LIMIT 1`,
      { repoId: query.repoId, sha: query.commitSHA ?? null });
    if (!found.records.length) return { snapshot: null, results: [], reason: 'no ready snapshot' };
    const snapshot = found.records[0].get('snapshot');
    if (snapshot.semanticStatus !== 'ready') return { snapshot: null, results: [], reason: 'semantic layer not ready for this snapshot' };
    const vector = await embed(query.query);
    validateEmbedding({ id: 'query', embedding: vector }, SEMANTIC_CONFIG.dimension);
    return await session.executeRead(async tx => {
      const hits = await tx.run(`CALL db.index.vector.queryNodes('context_chunk_embedding', $fetch, $vector) YIELD node, score
        WITH collect({node: node, score: score}) AS fetched
        WITH size(fetched) AS fetchedCount, [x IN fetched WHERE x.node.snapshotId = $id] AS mine
        RETURN fetchedCount, size(mine) AS matched,
          [x IN mine[..$topK] | {id: x.node.id, file: x.node.file, startLine: x.node.startLine, endLine: x.node.endLine,
            score: x.score, truncated: x.node.truncated, tokenTruncated: coalesce(x.node.tokenTruncated, false),
            embeddedChars: x.node.embeddedChars, charCount: x.node.charCount}] AS top`,
        { id: snapshot.id, vector, fetch: neo4j.int(SEARCH_FETCH), topK: neo4j.int(query.topK) });
      const row = hits.records[0];
      const fetched = row.get('fetchedCount').toNumber();
      let matched = row.get('matched').toNumber();
      let top = row.get('top') as Record<string, any>[];
      let method = 'index';
      if (matched < query.topK && fetched >= SEARCH_FETCH) {
        // Other snapshots' vectors crowded this one out of the global top-N; score only this snapshot's chunks exactly.
        const exact = await tx.run(`MATCH (c:ContextChunk {snapshotId: $id}) WHERE c.embedding IS NOT NULL
          WITH c, vector.similarity.cosine(c.embedding, $vector) AS score ORDER BY score DESC
          WITH collect({node: c, score: score}) AS scored
          RETURN size(scored) AS total,
            [x IN scored[..$topK] | {id: x.node.id, file: x.node.file, startLine: x.node.startLine, endLine: x.node.endLine,
              score: x.score, truncated: x.node.truncated, tokenTruncated: coalesce(x.node.tokenTruncated, false),
              embeddedChars: x.node.embeddedChars, charCount: x.node.charCount}] AS top`,
          { id: snapshot.id, vector, topK: neo4j.int(query.topK) });
        matched = exact.records[0].get('total').toNumber();
        top = exact.records[0].get('top') as Record<string, any>[];
        method = 'exact-scan';
      }
      const symbols = await tx.run(`UNWIND $ids AS cid MATCH (c:ContextChunk {snapshotId: $id, id: cid})
        OPTIONAL MATCH (c)-[:DESCRIBES]->(e:ContextEntity)
        WITH cid, e ORDER BY e.sourceLocation, e.localId
        RETURN cid, collect(CASE WHEN e IS NULL THEN null ELSE {localId: e.localId, label: e.label, sourceLocation: e.sourceLocation} END)[..10] AS entities`,
        { id: snapshot.id, ids: top.map(t => t.id) });
      const entities = new Map(symbols.records.map(r => [r.get('cid') as string, (r.get('entities') as unknown[]).filter(Boolean)]));
      return { snapshot: { id: snapshot.id, commitSHA: snapshot.commitSHA, commitTimestamp: snapshot.commitTimestamp,
          model: snapshot.semanticModel, modelRevision: snapshot.semanticModelRevision },
        results: top.map(t => ({ ...t, startLine: neo4j.integer.toNumber(t.startLine), endLine: neo4j.integer.toNumber(t.endLine),
          embeddedChars: neo4j.integer.toNumber(t.embeddedChars), charCount: neo4j.integer.toNumber(t.charCount), entities: entities.get(t.id as string) ?? [] })),
        requested: query.topK, method, fetched, matched, filteredOut: method === 'index' ? fetched - matched : null,
        possiblyIncomplete: method === 'index' && matched < query.topK && fetched >= SEARCH_FETCH };
    }, { timeout: 5000 });
  } finally { await session.close(); }
}
