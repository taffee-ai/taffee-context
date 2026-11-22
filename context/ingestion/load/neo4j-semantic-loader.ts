import { randomUUID } from 'node:crypto';
import neo4j, { type ManagedTransaction } from 'neo4j-driver';
import type { Neo4jConnection } from '../../storage/neo4j/client.ts';
import { snapshotId } from '../../types.ts';
import { SEMANTIC_CONFIG, chunkSource, computeLinks, decideSemanticStart, semanticConfigHash, semanticContentHash,
  type Chunk, type ChunkEntity, type SemanticConfig } from '../chunks/chunker.ts';
import { collectSource } from '../chunks/collect.ts';
import { pythonEmbedder, type Embed, type EmbedderMeta } from '../embeddings/run-embedder.ts';

const LEASE_MS = 35 * 60_000;

export interface SemanticResult {
  id: string;
  status: 'created' | 'resumed' | 'restarted' | 'unchanged';
  chunks: number;
  truncated: number;
  tokenTruncated: number;
  links: number;
  embeddedNow: number;
  seconds: { collect: number; embed: number; total: number };
  embedder?: EmbedderMeta;
}

async function write<T>(connection: Neo4jConnection, work: (tx: ManagedTransaction) => Promise<T>, timeout = 30_000): Promise<T> {
  const session = connection.driver.session({ database: connection.database });
  try { return await session.executeWrite(work, { timeout }); }
  finally { await session.close(); }
}

async function begin(connection: Neo4jConnection, id: string, config: SemanticConfig, plan: { chunks: Chunk[]; links: number; contentHash: string }, owner: string) {
  const configHash = semanticConfigHash(config);
  return write(connection, async tx => {
    // Same repository write lock the structural loader takes; serializes semantic builders per repository.
    const found = await tx.run(`MATCH (s:ContextSnapshot {id: $id}) MATCH (r:ContextRepository {repoId: s.repoId})
      SET r.writeSequence = coalesce(r.writeSequence, 0) + 1
      RETURN s.ready AS ready, s.staged AS staged, s.semanticStatus AS status, s.semanticConfigHash AS configHash,
        s.semanticContentHash AS contentHash, s.semanticLeaseExpires AS lease`, { id });
    if (!found.records.length || (found.records[0].get('ready') !== true && found.records[0].get('staged') !== true)) {
      throw new Error('A ready structural snapshot is required before chunk-embed');
    }
    const row = found.records[0];
    const start = decideSemanticStart({ status: row.get('status'), configHash: row.get('configHash'), contentHash: row.get('contentHash') },
      configHash, plan.contentHash);
    if (start === 'unchanged') return start;
    const lease = row.get('lease');
    if (start !== 'new' && lease !== null && Number(lease) > Date.now()) throw new Error('Semantic build already in progress for this snapshot');
    if (start === 'restart') await tx.run('MATCH (:ContextSnapshot {id: $id})-[:HAS_CHUNK]->(c:ContextChunk) DETACH DELETE c', { id });
    await tx.run(`MATCH (s:ContextSnapshot {id: $id}) REMOVE s.semanticTokenTruncatedCount, s.semanticTimestamp
      SET s.semanticStatus = 'building', s.semanticConfigHash = $configHash,
      s.semanticContentHash = $contentHash, s.semanticModel = $model, s.semanticModelRevision = $modelRevision,
      s.semanticCodeRevision = $codeRevision, s.semanticDimension = $dimension, s.semanticChunkLines = $chunkLines, s.semanticMaxChunkChars = $maxChunkChars,
      s.semanticMaxEmbedChars = $maxEmbedChars, s.semanticMaxEmbedTokens = $maxEmbedTokens, s.semanticExtensions = $extensions, s.semanticChunkCount = $chunkCount,
      s.semanticTruncatedCount = $truncatedCount, s.semanticLinkCount = $linkCount,
      s.semanticLeaseOwner = $owner, s.semanticLeaseExpires = $expires`, {
      id, configHash, contentHash: plan.contentHash, model: config.model, modelRevision: config.modelRevision,
      codeRevision: config.codeRevision, dimension: neo4j.int(config.dimension), chunkLines: neo4j.int(config.chunkLines), maxChunkChars: neo4j.int(config.maxChunkChars),
      maxEmbedChars: neo4j.int(config.maxEmbedChars), maxEmbedTokens: neo4j.int(config.maxEmbedTokens), extensions: [...config.extensions].sort(),
      chunkCount: neo4j.int(plan.chunks.length), truncatedCount: neo4j.int(plan.chunks.filter(c => c.truncated).length),
      linkCount: neo4j.int(plan.links), owner, expires: neo4j.int(Date.now() + LEASE_MS) });
    return start === 'new' ? 'created' as const : start === 'restart' ? 'restarted' as const : 'resumed' as const;
  });
}

async function writeBatch(connection: Neo4jConnection, id: string, owner: string, rows: { chunk: Chunk; embedding: number[]; tokens?: number; tokenTruncated?: boolean }[]) {
  await write(connection, async tx => {
    const held = await tx.run(`MATCH (s:ContextSnapshot {id: $id, semanticStatus: 'building', semanticLeaseOwner: $owner})
      SET s.semanticLeaseExpires = $expires RETURN count(s) AS held`, { id, owner, expires: neo4j.int(Date.now() + LEASE_MS) });
    if (held.records[0].get('held').toNumber() !== 1) throw new Error('Semantic build lease lost');
    await tx.run(`MATCH (s:ContextSnapshot {id: $id}) UNWIND $rows AS r
      MERGE (c:ContextChunk {snapshotId: $id, id: r.id})
      SET c.file = r.file, c.startLine = r.startLine, c.endLine = r.endLine, c.charCount = r.charCount,
        c.embeddedChars = r.embeddedChars, c.truncated = r.truncated, c.embeddedTokens = r.embeddedTokens,
        c.tokenTruncated = r.tokenTruncated, c.embedding = r.embedding
      MERGE (s)-[:HAS_CHUNK]->(c)`, { id, rows: rows.map(({ chunk, embedding, tokens, tokenTruncated }) => ({ id: chunk.id, file: chunk.file,
        startLine: neo4j.int(chunk.startLine), endLine: neo4j.int(chunk.endLine), charCount: neo4j.int(chunk.charCount),
        embeddedChars: neo4j.int(chunk.embeddedChars), truncated: chunk.truncated, embeddedTokens: tokens === undefined ? null : neo4j.int(tokens),
        tokenTruncated: tokenTruncated ?? false, embedding })) });
  });
}

async function finalize(connection: Neo4jConnection, id: string, owner: string, chunks: Chunk[], links: { chunkId: string; localId: string }[]): Promise<number> {
  return write(connection, async tx => {
    const held = await tx.run(`MATCH (s:ContextSnapshot {id: $id, semanticStatus: 'building', semanticLeaseOwner: $owner})
      RETURN s.semanticChunkCount AS planned`, { id, owner });
    if (!held.records.length) throw new Error('Semantic build lease lost');
    const counts = await tx.run(`MATCH (c:ContextChunk {snapshotId: $id})
      RETURN count(c) AS total, count(c.embedding) AS embedded, sum(CASE WHEN c.truncated THEN 1 ELSE 0 END) AS truncated,
        sum(CASE WHEN c.tokenTruncated THEN 1 ELSE 0 END) AS tokenTruncated`, { id });
    const row = counts.records[0];
    if (row.get('total').toNumber() !== chunks.length || row.get('embedded').toNumber() !== chunks.length
        || row.get('truncated').toNumber() !== chunks.filter(c => c.truncated).length) {
      throw new Error('Stored chunks do not match the planned chunk set');
    }
    for (let i = 0; i < links.length; i += 500) {
      await tx.run(`UNWIND $links AS l
        MATCH (c:ContextChunk {snapshotId: $id, id: l.chunkId}) MATCH (e:ContextEntity {snapshotId: $id, localId: l.localId})
        CREATE (c)-[:DESCRIBES]->(e)`, { id, links: links.slice(i, i + 500) });
    }
    const made = await tx.run('MATCH (:ContextChunk {snapshotId: $id})-[d:DESCRIBES]->() RETURN count(d) AS links', { id });
    if (made.records[0].get('links').toNumber() !== links.length) throw new Error('Chunk links do not match the planned links');
    const tokenTruncated = row.get('tokenTruncated').toNumber() as number;
    // Readers see semanticStatus and the links together at commit.
    await tx.run(`MATCH (s:ContextSnapshot {id: $id}) SET s.semanticStatus = 'ready', s.semanticTimestamp = $now,
      s.semanticTokenTruncatedCount = $tokenTruncated
      REMOVE s.semanticLeaseOwner, s.semanticLeaseExpires`, { id, now: new Date().toISOString(), tokenTruncated: neo4j.int(tokenTruncated) });
    return tokenTruncated;
  }, 120_000);
}

async function release(connection: Neo4jConnection, id: string, owner: string): Promise<void> {
  await write(connection, async tx => {
    await tx.run(`MATCH (s:ContextSnapshot {id: $id, semanticStatus: 'building', semanticLeaseOwner: $owner})
      REMOVE s.semanticLeaseOwner, s.semanticLeaseExpires`, { id, owner });
  }).catch(() => {});
}

/** Builds the semantic layer for an already loaded, ready structural snapshot. Safe to re-run and to resume. */
export async function buildSemanticLayer(connection: Neo4jConnection, input: { repoId: string; repositoryPath: string; commitSHA: string },
  options: { embed?: Embed; config?: SemanticConfig; signal?: AbortSignal } = {}): Promise<SemanticResult> {
  const started = performance.now();
  const config = options.config ?? SEMANTIC_CONFIG;
  const id = snapshotId(input.repoId, input.commitSHA);
  const files = await collectSource(input, { config, signal: options.signal });
  const collected = performance.now();
  const chunks = chunkSource(id, files, config);

  const session = connection.driver.session({ database: connection.database });
  let entities: ChunkEntity[];
  try {
    const found = await session.run(`MATCH (s:ContextSnapshot {id: $id})-[:HAS_ENTITY]->(e:ContextEntity)
      WHERE s.ready = true OR s.staged = true
      RETURN e.localId AS localId, e.sourceFile AS sourceFile, e.sourceLocation AS sourceLocation`, { id });
    entities = found.records.map(r => ({ localId: r.get('localId'), sourceFile: r.get('sourceFile') ?? '', sourceLocation: r.get('sourceLocation') ?? '' }));
  } finally { await session.close(); }
  const links = computeLinks(chunks, entities);
  const contentHash = semanticContentHash(config, chunks, links);
  const done = (status: SemanticResult['status'], embeddedNow: number, embedder?: EmbedderMeta, embedMs = 0): SemanticResult => ({
    id, status, chunks: chunks.length, truncated: chunks.filter(c => c.truncated).length, tokenTruncated: 0, links: links.length, embeddedNow,
    seconds: { collect: (collected - started) / 1000, embed: embedMs / 1000, total: (performance.now() - started) / 1000 }, embedder });

  const owner = randomUUID();
  const start = await begin(connection, id, config, { chunks, links: links.length, contentHash }, owner);
  if (start === 'unchanged') {
    const reader = connection.driver.session({ database: connection.database });
    try {
      const stored = await reader.run('MATCH (s:ContextSnapshot {id: $id}) RETURN s.semanticTokenTruncatedCount AS n', { id });
      const n = stored.records[0].get('n');
      return { ...done('unchanged', 0), tokenTruncated: n === null ? 0 : n.toNumber() };
    } finally { await reader.close(); }
  }

  const byId = new Map(chunks.map(c => [c.id, c]));
  let embeddedNow = 0;
  let embedder: EmbedderMeta | undefined;
  let embedMs = 0;
  let tokenTruncated = 0;
  try {
    const reader = connection.driver.session({ database: connection.database });
    let have: Set<string>;
    try {
      const rows = await reader.run('MATCH (c:ContextChunk {snapshotId: $id}) WHERE c.embedding IS NOT NULL RETURN c.id AS id', { id });
      have = new Set(rows.records.map(r => r.get('id') as string));
    } finally { await reader.close(); }
    const todo = chunks.filter(c => !have.has(c.id));
    const embedStarted = performance.now();
    if (todo.length) {
      const embed = options.embed ?? pythonEmbedder({ config });
      embedder = await embed(todo.map(c => ({ id: c.id, text: c.text })), async rows => {
        await writeBatch(connection, id, owner, rows.map(r => ({ chunk: byId.get(r.id)!, embedding: r.embedding, tokens: r.tokens, tokenTruncated: r.tokenTruncated })));
        embeddedNow += rows.length;
      }, options.signal);
    }
    embedMs = performance.now() - embedStarted;
    tokenTruncated = await finalize(connection, id, owner, chunks, links);
  } catch (error) {
    await release(connection, id, owner);
    throw error;
  }
  return { ...done(start, embeddedNow, embedder, embedMs), tokenTruncated };
}
