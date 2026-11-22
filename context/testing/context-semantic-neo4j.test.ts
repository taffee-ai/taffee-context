import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { connectNeo4j, type Neo4jConnection } from '../storage/neo4j/client.ts';
import { initializeSchema } from '../storage/neo4j/schema.ts';
import { loadSnapshot } from '../ingestion/load/neo4j-loader.ts';
import { buildSemanticLayer } from '../ingestion/load/neo4j-semantic-loader.ts';
import { searchChunks } from '../retrieval/query/neo4j-search.ts';
import { SEMANTIC_CONFIG } from '../ingestion/chunks/chunker.ts';
import type { Embed } from '../ingestion/embeddings/run-embedder.ts';
import { snapshotId, type RepositorySnapshot } from '../types.ts';

const enabled = process.env.TAFFEE_NEO4J_TEST === '1';

function fakeVector(text: string): number[] {
  const h = createHash('sha512').update(text).digest();
  const v = Array.from({ length: 768 }, (_, i) => (h[i % 64] - 127.5) / 127.5 + ((i % 7) + 1) * 0.001);
  const norm = Math.sqrt(v.reduce((s, x) => s + x * x, 0));
  return v.map(x => x / norm);
}
function fakeEmbed(seen: string[] = [], failAfter = Infinity, tokenCut: (id: string) => boolean = () => false): Embed {
  return async (items, onRows) => {
    let done = 0;
    for (let i = 0; i < items.length; i += 1) {
      if (done >= failAfter) throw new Error('boom: simulated interruption');
      seen.push(items[i].id);
      await onRows([{ id: items[i].id, embedding: fakeVector(items[i].text), tokens: Math.ceil(items[i].text.length / 4), tokenTruncated: tokenCut(items[i].id) }]);
      done += 1;
    }
    return undefined;
  };
}
const numbered = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => `value_${from + i} = ${from + i}`).join('\n');

async function makeRepo(files: Record<string, string>, root?: string) {
  const dir = root ?? await mkdtemp(join(tmpdir(), 'semantic-fixture-'));
  const git = (...args: string[]) => execFileSync('git', args, { cwd: dir, encoding: 'utf8' }).trim();
  if (!root) { git('init', '-q'); git('config', 'user.email', 'fixture@example.invalid'); git('config', 'user.name', 'Fixture'); }
  for (const [path, text] of Object.entries(files)) await writeFile(join(dir, path), text);
  git('add', '.'); git('commit', '-qm', 'fixture');
  return { dir, sha: git('rev-parse', 'HEAD') };
}
function structural(repoId: string, sha: string, timestamp: string, dir: string): RepositorySnapshot {
  return { repoId, commitSHA: sha, commitTimestamp: timestamp, repositoryPath: dir, graphifyVersion: '0.9.51',
    nodes: [{ id: 'f1', label: 'f1', kind: 'function', sourceFile: 'app.py', sourceLocation: 'L5' },
      { id: 'f2', label: 'f2', kind: 'function', sourceFile: 'app.py', sourceLocation: 'L160' },
      { id: 'f3', label: 'f3', kind: 'function', sourceFile: 'util.py', sourceLocation: 'L3' }],
    edges: [{ source: 'f1', target: 'f2', relation: 'calls', confidence: 'EXTRACTED', sourceFile: 'app.py', sourceLocation: 'L6' }] };
}
const FILES = { 'app.py': numbered(1, 200) + '\n', 'util.py': numbered(1, 10) + '\n' };

async function cleanup(c: Neo4jConnection, repoIds: string[]) {
  const s = c.driver.session({ database: c.database });
  try {
    await s.run('MATCH (s:ContextSnapshot)-[:HAS_CHUNK]->(k:ContextChunk) WHERE s.repoId IN $ids DETACH DELETE k', { ids: repoIds });
    await s.run('MATCH (s:ContextSnapshot)-[:HAS_ENTITY]->(n:ContextEntity) WHERE s.repoId IN $ids DETACH DELETE n', { ids: repoIds });
    await s.run('MATCH (s:ContextSnapshot) WHERE s.repoId IN $ids DETACH DELETE s', { ids: repoIds });
    await s.run('MATCH (r:ContextRepository) WHERE r.repoId IN $ids DETACH DELETE r', { ids: repoIds });
  } finally { await s.close(); }
}
async function snapshotProps(c: Neo4jConnection, id: string): Promise<Record<string, any>> {
  const s = c.driver.session({ database: c.database });
  try { return (await s.run('MATCH (s:ContextSnapshot {id: $id}) RETURN properties(s) AS p', { id })).records[0].get('p'); }
  finally { await s.close(); }
}
async function count(c: Neo4jConnection, cypher: string, params: Record<string, unknown>): Promise<number> {
  const s = c.driver.session({ database: c.database });
  try { return (await s.run(cypher, params)).records[0].get('n').toNumber(); }
  finally { await s.close(); }
}

test('semantic layer: idempotent re-run, links, stored config and search', { skip: !enabled }, async () => {
  const c = connectNeo4j();
  const repo = `sem-test-${randomUUID()}`;
  const { dir, sha } = await makeRepo(FILES);
  try {
    await initializeSchema(c);
    await loadSnapshot(c, structural(repo, sha, '2026-01-01T00:00:00.000Z', dir));
    const seen: string[] = [];
    const first = await buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed(seen) });
    assert.deepEqual([first.status, first.chunks, first.truncated, first.links, first.embeddedNow], ['created', 3, 0, 3, 3]);
    const again = await buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed(seen) });
    assert.deepEqual([again.status, again.embeddedNow], ['unchanged', 0]);
    assert.equal(seen.length, 3, 'unchanged re-run must not embed');

    const id = snapshotId(repo, sha);
    const props = await snapshotProps(c, id);
    assert.equal(props.semanticStatus, 'ready');
    assert.equal(props.semanticModel, SEMANTIC_CONFIG.model); assert.equal(props.semanticModelRevision, SEMANTIC_CONFIG.modelRevision);
    assert.equal(props.semanticCodeRevision, SEMANTIC_CONFIG.codeRevision);
    assert.equal(props.semanticDimension.toNumber(), 768); assert.equal(props.semanticChunkLines.toNumber(), 150);
    assert.equal(props.semanticChunkCount.toNumber(), 3); assert.equal(props.semanticLinkCount.toNumber(), 3);
    assert.equal(props.semanticLeaseOwner, undefined);
    assert.equal(await count(c, 'MATCH (:ContextChunk {snapshotId: $id})-[d:DESCRIBES]->() RETURN count(d) AS n', { id }), 3);
    assert.equal(await count(c, 'MATCH (k:ContextChunk {snapshotId: $id}) WHERE k.text IS NOT NULL RETURN count(k) AS n', { id }), 0, 'chunk text must not be stored');

    const result: any = await searchChunks(c, { repoId: repo, query: 'q', topK: 8 }, async () => fakeVector(numbered(151, 200)));
    assert.equal(result.snapshot.id, id);
    assert.equal(result.results[0].file, 'app.py'); assert.equal(result.results[0].startLine, 151); assert.equal(result.results[0].endLine, 200);
    assert.ok(result.results[0].score > 0.99);
    assert.deepEqual(result.results[0].entities.map((e: any) => e.localId), ['f2']);
    assert.equal(result.matched, 3); assert.equal(result.requested, 8); assert.equal(result.possiblyIncomplete, false);
  } finally { await cleanup(c, [repo]); await c.close(); await rm(dir, { recursive: true, force: true }); }
});

test('semantic layer: interrupted run is not searchable, leaves no links, and resumes only the missing chunks', { skip: !enabled }, async () => {
  const c = connectNeo4j();
  const repo = `sem-test-${randomUUID()}`;
  const { dir, sha } = await makeRepo(FILES);
  const id = snapshotId(repo, sha);
  try {
    await initializeSchema(c);
    await loadSnapshot(c, structural(repo, sha, '2026-01-01T00:00:00.000Z', dir));
    await assert.rejects(buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed([], 1) }), /boom/);
    assert.equal((await snapshotProps(c, id)).semanticStatus, 'building');
    assert.equal((await snapshotProps(c, id)).semanticLeaseOwner, undefined, 'lease released after failure');
    assert.equal(await count(c, 'MATCH (k:ContextChunk {snapshotId: $id}) RETURN count(k.embedding) AS n', { id }), 1);
    assert.equal(await count(c, 'MATCH (:ContextChunk {snapshotId: $id})-[d:DESCRIBES]->() RETURN count(d) AS n', { id }), 0);
    const hidden: any = await searchChunks(c, { repoId: repo, query: 'q', topK: 8 }, async () => fakeVector(numbered(1, 150)));
    assert.equal(hidden.snapshot, null); assert.deepEqual(hidden.results, []); assert.match(hidden.reason, /not ready/);

    const seen: string[] = [];
    const resumed = await buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed(seen) });
    assert.deepEqual([resumed.status, resumed.embeddedNow, seen.length], ['resumed', 2, 2]);
    assert.equal((await snapshotProps(c, id)).semanticStatus, 'ready');
    assert.equal(await count(c, 'MATCH (:ContextChunk {snapshotId: $id})-[d:DESCRIBES]->() RETURN count(d) AS n', { id }), 3);
    const visible: any = await searchChunks(c, { repoId: repo, query: 'q', topK: 8 }, async () => fakeVector(numbered(1, 150)));
    assert.equal(visible.results[0].startLine, 1);
  } finally { await cleanup(c, [repo]); await c.close(); await rm(dir, { recursive: true, force: true }); }
});

test('semantic layer: an incomplete layer restarts under a new token cap and records token truncation; a complete one is immutable', { skip: !enabled }, async () => {
  const c = connectNeo4j();
  const repo = `sem-test-${randomUUID()}`;
  const { dir, sha } = await makeRepo(FILES);
  const id = snapshotId(repo, sha);
  const capped = { ...SEMANTIC_CONFIG, maxEmbedTokens: 2048 };
  try {
    await initializeSchema(c);
    await loadSnapshot(c, structural(repo, sha, '2026-01-01T00:00:00.000Z', dir));
    await assert.rejects(buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed([], 1) }), /boom/);
    assert.equal(await count(c, 'MATCH (k:ContextChunk {snapshotId: $id}) RETURN count(k) AS n', { id }), 1);
    const seen: string[] = [];
    const restarted = await buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha },
      { embed: fakeEmbed(seen, Infinity, chunk => chunk.endsWith('::151')), config: capped });
    assert.deepEqual([restarted.status, restarted.embeddedNow, restarted.tokenTruncated, seen.length], ['restarted', 3, 1, 3]);
    const props = await snapshotProps(c, id);
    assert.equal(props.semanticStatus, 'ready'); assert.equal(props.semanticMaxEmbedTokens.toNumber(), 2048);
    assert.equal(props.semanticTokenTruncatedCount.toNumber(), 1);
    const found: any = await searchChunks(c, { repoId: repo, query: 'q', topK: 8 }, async () => fakeVector(numbered(151, 200)));
    assert.equal(found.results[0].startLine, 151); assert.equal(found.results[0].tokenTruncated, true);
    assert.equal(found.results.filter((r: any) => r.tokenTruncated).length, 1);
    const same = await buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed(), config: capped });
    assert.deepEqual([same.status, same.tokenTruncated], ['unchanged', 1]);
    await assert.rejects(buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed() }), /Immutable semantic config conflict/);
  } finally { await cleanup(c, [repo]); await c.close(); await rm(dir, { recursive: true, force: true }); }
});

test('semantic layer: a concurrent builder is refused while the lease is held', { skip: !enabled }, async () => {
  const c = connectNeo4j();
  const repo = `sem-test-${randomUUID()}`;
  const { dir, sha } = await makeRepo(FILES);
  try {
    await initializeSchema(c);
    await loadSnapshot(c, structural(repo, sha, '2026-01-01T00:00:00.000Z', dir));
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const slow: Embed = async (items, onRows) => { await gate; await fakeEmbed()(items, onRows); return undefined; };
    const first = buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: slow });
    for (let i = 0; i < 100 && (await snapshotProps(c, snapshotId(repo, sha))).semanticLeaseOwner === undefined; i += 1) {
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    const second = await buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed() }).then(() => 'ran', (e: Error) => e.message);
    assert.match(second, /already in progress/);
    release();
    assert.equal((await first).status, 'created');
  } finally { await cleanup(c, [repo]); await c.close(); await rm(dir, { recursive: true, force: true }); }
});

test('semantic search: no leakage across repositories or commits, and underfill is reported', { skip: !enabled }, async () => {
  const c = connectNeo4j();
  const repoA = `sem-test-${randomUUID()}`, repoB = `${repoA}-other`, notBuilt = `${repoA}-structural`;
  const a1 = await makeRepo(FILES);
  const a2 = await makeRepo({ 'app.py': numbered(1, 200) + '\n# second commit\n' }, a1.dir);
  const b = await makeRepo(FILES); // identical content: identical vectors in another repository
  try {
    await initializeSchema(c);
    await loadSnapshot(c, structural(repoA, a1.sha, '2026-01-01T00:00:00.000Z', a1.dir));
    await loadSnapshot(c, structural(repoA, a2.sha, '2026-02-01T00:00:00.000Z', a1.dir));
    await loadSnapshot(c, structural(repoB, b.sha, '2026-03-01T00:00:00.000Z', b.dir));
    await loadSnapshot(c, structural(notBuilt, b.sha, '2026-03-01T00:00:00.000Z', b.dir));
    for (const [repo, x] of [[repoA, a1], [repoA, a2], [repoB, b]] as const) {
      await buildSemanticLayer(c, { repoId: repo, repositoryPath: x.dir, commitSHA: x.sha }, { embed: fakeEmbed() });
    }
    const probe = async () => fakeVector(numbered(151, 200));
    const inRepoA1: any = await searchChunks(c, { repoId: repoA, query: 'q', commitSHA: a1.sha, topK: 25 }, probe);
    assert.ok(inRepoA1.results.length > 0);
    assert.ok(inRepoA1.results.every((r: any) => r.id.startsWith(`["${repoA}","${a1.sha}"]::`)), 'only the requested commit');
    assert.equal(inRepoA1.matched, 3); assert.equal(inRepoA1.requested, 25);
    // Depending on how many foreign vectors the shared index holds, the index path filters others out (filteredOut) or the exact scan runs (no filtering needed).
    if (inRepoA1.method === 'index') assert.ok(inRepoA1.filteredOut >= 6, 'other commit and other repository were fetched then filtered out');
    else assert.equal(inRepoA1.filteredOut, null);
    assert.equal(inRepoA1.possiblyIncomplete, false);

    const latest: any = await searchChunks(c, { repoId: repoA, query: 'q', topK: 25 }, probe);
    assert.equal(latest.snapshot.commitSHA, a2.sha, 'omitted commit resolves to the latest semantic-ready commit');
    assert.ok(latest.results.every((r: any) => r.id.startsWith(`["${repoA}","${a2.sha}"]::`)));
    const inRepoB: any = await searchChunks(c, { repoId: repoB, query: 'q', topK: 25 }, probe);
    assert.ok(inRepoB.results.every((r: any) => r.id.startsWith(`["${repoB}","${b.sha}"]::`)));
    const missing: any = await searchChunks(c, { repoId: notBuilt, query: 'q', topK: 5 }, probe);
    assert.equal(missing.snapshot, null); assert.match(missing.reason, /not ready/);
    const unknown: any = await searchChunks(c, { repoId: `${repoA}-nope`, query: 'q', topK: 5 }, probe);
    assert.equal(unknown.snapshot, null); assert.match(unknown.reason, /no ready snapshot/);
  } finally { await cleanup(c, [repoA, repoB, notBuilt]); await c.close(); for (const d of [a1.dir, b.dir]) await rm(d, { recursive: true, force: true }); }
});

test('semantic search: falls back to an exact scan when other snapshots crowd the global index', { skip: !enabled }, async () => {
  const c = connectNeo4j();
  const repo = `sem-test-${randomUUID()}`;
  const { dir, sha } = await makeRepo(FILES);
  const crowd = `crowd-${randomUUID()}`;
  try {
    await initializeSchema(c);
    await loadSnapshot(c, structural(repo, sha, '2026-01-01T00:00:00.000Z', dir));
    await buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed() });
    const probe = fakeVector(numbered(151, 200));
    // 700 foreign vectors almost identical to the probe outrank this repo's chunks in the global top 600.
    const session = c.driver.session({ database: c.database });
    try {
      for (let start = 0; start < 700; start += 100) {
        await session.run(`UNWIND range($from, $to) AS i CREATE (:ContextChunk {snapshotId: $crowd, id: $crowd + '::' + toString(i), file: 'x', startLine: 1, endLine: 1,
          charCount: 1, embeddedChars: 1, truncated: false, embedding: [x IN $probe | x + 0.0001 * (i % 7)]})`, { from: start, to: start + 99, crowd, probe });
      }
    } finally { await session.close(); }
    const result: any = await searchChunks(c, { repoId: repo, query: 'q', topK: 3 }, async () => probe);
    assert.equal(result.method, 'exact-scan'); assert.equal(result.possiblyIncomplete, false);
    assert.equal(result.matched, 3); assert.equal(result.results.length, 3);
    assert.equal(result.results[0].startLine, 151); assert.ok(result.results[0].score > 0.99);
    assert.ok(result.results.every((r: any) => r.id.startsWith(`["${repo}","${sha}"]::`)), 'only the requested snapshot');
  } finally {
    const cleanupSession = c.driver.session({ database: c.database });
    try { await cleanupSession.run('MATCH (k:ContextChunk {snapshotId: $crowd}) DETACH DELETE k', { crowd }); } finally { await cleanupSession.close(); }
    await cleanup(c, [repo]); await c.close(); await rm(dir, { recursive: true, force: true });
  }
});

test('semantic layer: config change on a complete snapshot is refused, and a structural snapshot is required', { skip: !enabled }, async () => {
  const c = connectNeo4j();
  const repo = `sem-test-${randomUUID()}`;
  const { dir, sha } = await makeRepo(FILES);
  const id = snapshotId(repo, sha);
  try {
    await initializeSchema(c);
    await assert.rejects(buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed() }), /ready structural snapshot/);
    await loadSnapshot(c, structural(repo, sha, '2026-01-01T00:00:00.000Z', dir));
    await buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed() });
    const seen: string[] = [];
    for (const changed of [{ ...SEMANTIC_CONFIG, chunkLines: 100 }, { ...SEMANTIC_CONFIG, modelRevision: 'b'.repeat(40) },
      { ...SEMANTIC_CONFIG, maxEmbedChars: 4000 }]) {
      await assert.rejects(buildSemanticLayer(c, { repoId: repo, repositoryPath: dir, commitSHA: sha }, { embed: fakeEmbed(seen), config: changed }),
        /Immutable semantic config conflict/);
    }
    assert.equal(seen.length, 0);
    const props = await snapshotProps(c, id);
    assert.equal(props.semanticStatus, 'ready'); assert.equal(props.semanticChunkLines.toNumber(), 150);
    assert.equal(props.semanticModelRevision, SEMANTIC_CONFIG.modelRevision);
  } finally { await cleanup(c, [repo]); await c.close(); await rm(dir, { recursive: true, force: true }); }
});
