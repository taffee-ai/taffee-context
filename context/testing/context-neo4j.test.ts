import { test } from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, writeFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { connectNeo4j, type Neo4jConnection } from '../storage/neo4j/client.ts';
import { initializeSchema } from '../storage/neo4j/schema.ts';
import { loadSnapshot } from '../ingestion/load/neo4j-loader.ts';
import { queryGraph } from '../retrieval/query/neo4j-query.ts';
import { extractRepository } from '../ingestion/extract/code/graphify-extractor.ts';
import { graphQueryTool } from '../retrieval/query/graph-query-tool.ts';
import type { RepositorySnapshot } from '../types.ts';

const enabled = process.env.TAFFEE_NEO4J_TEST === '1';
function fixture(repoId: string): RepositorySnapshot {
  return { repoId, commitSHA: 'a'.repeat(40), commitTimestamp: '2026-01-01T00:00:00.000Z', repositoryPath: '/fixture', graphifyVersion: '0.9.51',
    nodes: [{ id: 'caller', label: 'caller', kind: 'function', sourceFile: 'app.py', sourceLocation: 'L1' },
      { id: 'callee', label: 'callee', kind: 'function', sourceFile: 'app.py', sourceLocation: 'L4' }],
    edges: [{ source: 'caller', target: 'callee', relation: 'calls', confidence: 'EXTRACTED', sourceFile: 'app.py', sourceLocation: 'L2' }] };
}
async function cleanup(c: Neo4jConnection, repoIds: string[]) {
  const s = c.driver.session({ database: c.database });
  try {
    await s.run(`MATCH (r:ContextRepository)-[:HAS_SNAPSHOT]->(s:ContextSnapshot)-[:HAS_ENTITY]->(n:ContextEntity)
      WHERE r.repoId IN $ids DETACH DELETE n`, { ids: repoIds });
    await s.run('MATCH (s:ContextSnapshot) WHERE s.repoId IN $ids DETACH DELETE s', { ids: repoIds });
    await s.run('MATCH (r:ContextRepository) WHERE r.repoId IN $ids DETACH DELETE r', { ids: repoIds });
  } finally { await s.close(); }
}
test('Neo4j: atomic ingestion, concurrency, immutable versions, scoped queries and rollback', { skip: !enabled }, async () => {
  const c = connectNeo4j();
  const repo = `s8p2-test-${randomUUID()}`, other = `${repo}-other`, broken = `${repo}-broken`;
  try {
    await initializeSchema(c); await initializeSchema(c);
    const input = fixture(repo);
    const concurrent = await Promise.all([loadSnapshot(c, input), loadSnapshot(c, input)]);
    assert.deepEqual(concurrent.map(x => x.status).sort(), ['created', 'unchanged']);
    await assert.rejects(loadSnapshot(c, { ...input, nodes: input.nodes.map(n => ({ ...n, label: 'changed' })) }), /Immutable/);
    await loadSnapshot(c, { ...input, commitSHA: 'b'.repeat(40), commitTimestamp: '2026-02-01T00:00:00Z', edges: [] });
    await loadSnapshot(c, { ...input, commitSHA: 'd'.repeat(40), commitTimestamp: '2025-01-01T00:00:00Z' });
    await loadSnapshot(c, fixture(other));
    const latest: any = await queryGraph(c, { repoId: repo, operation: 'resolve' });
    assert.equal(latest.snapshot.commitSHA, 'b'.repeat(40));
    // Re-ingesting older versions must never make them current.
    assert.equal((await loadSnapshot(c, input)).status, 'unchanged');
    const calls: any = await queryGraph(c, { repoId: repo, commitSHA: input.commitSHA, operation: 'get_callees', symbol: 'caller' });
    assert.equal(calls.results.length, 1); assert.equal(calls.results[0].entity.localId, 'callee');
    assert.equal(calls.results[0].confidence, 'EXTRACTED');
    const incoming: any = await queryGraph(c, { repoId: repo, commitSHA: input.commitSHA, operation: 'get_callers', symbol: 'callee' });
    assert.equal(incoming.results[0].entity.localId, 'caller');
    const current: any = await queryGraph(c, { repoId: repo, operation: 'get_callees', symbol: 'caller' });
    assert.equal(current.results.length, 0);
    const bounded: any = await queryGraph(c, { repoId: repo, operation: 'find_symbol', symbol: 'call', limit: 1 });
    assert.equal(bounded.results.length, 1); assert.equal(bounded.truncated, true);
    const literal: any = await queryGraph(c, { repoId: repo, operation: 'find_symbol', symbol: "' OR true //" });
    assert.equal(literal.results.length, 0);
    const missing: any = await queryGraph(c, { repoId: repo, commitSHA: 'c'.repeat(40), operation: 'resolve' });
    assert.equal(missing.snapshot, null);
    const oldAllowlist = process.env.TAFFEE_CONTEXT_REPOS;
    process.env.TAFFEE_CONTEXT_REPOS = JSON.stringify([repo]);
    try {
      const dispatched = JSON.parse(await graphQueryTool({ repoId: repo, operation: 'find_symbol', symbol: 'caller' }));
      assert.equal(dispatched.results.length, 1);
    } finally {
      if (oldAllowlist === undefined) delete process.env.TAFFEE_CONTEXT_REPOS;
      else process.env.TAFFEE_CONTEXT_REPOS = oldAllowlist;
    }
    // Inject an error after real node writes within the real managed transaction.
    const originalSession = c.driver.session.bind(c.driver);
    const fault = { ...c, driver: { session: (options: any) => {
      const session = originalSession(options);
      return { close: () => session.close(), executeWrite: (work: any, config: any) => session.executeWrite(tx => work({
        run: async (statement: string, params: any) => {
          const result = await tx.run(statement, params);
          if (statement.includes('CREATE (s)-[:HAS_ENTITY]')) throw new Error('injected load failure');
          return result;
        },
      }), config) };
    } } } as unknown as Neo4jConnection;
    await assert.rejects(loadSnapshot(fault, fixture(broken)), /injected/);
    assert.equal((await queryGraph(c, { repoId: broken, operation: 'resolve' })).snapshot, null);
    const inspection = c.driver.session({ database: c.database });
    try {
      const count = await inspection.run('MATCH (n:ContextEntity {snapshotId: $id}) RETURN count(n) AS count', { id: JSON.stringify([broken, input.commitSHA]) });
      assert.equal(count.records[0].get('count').toNumber(), 0);
    } finally { await inspection.close(); }
    assert.equal((await loadSnapshot(c, fixture(broken))).status, 'created');
  } finally { await cleanup(c, [repo, other, broken]); await c.close(); }
});
test('real Graphify extracts exact committed code and rejects symlinks', { skip: !enabled }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'context-fixture-'));
  const repoId = `s8p2-extract-${randomUUID()}`;
  const c = connectNeo4j();
  const git = (...args: string[]) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
  try {
    git('init', '-q'); git('config', 'user.email', 'fixture@example.invalid'); git('config', 'user.name', 'Fixture');
    await writeFile(join(root, 'app.py'), 'def callee():\n    return 1\n\ndef caller():\n    return callee()\n');
    git('add', '.'); git('commit', '-qm', 'fixture');
    const sha = git('rev-parse', 'HEAD');
    await writeFile(join(root, 'untracked.py'), 'def do_not_ingest():\n    return 2\n');
    const graph = await extractRepository({ repoId, repositoryPath: root, commitSHA: sha });
    assert.equal(graph.commitSHA, sha); assert.ok(graph.nodes.some(n => n.label === 'caller()'));
    assert.ok(!graph.nodes.some(n => n.label.includes('do_not_ingest')));
    assert.ok(graph.edges.some(e => e.relation === 'calls'));
    await initializeSchema(c); await loadSnapshot(c, graph);
    const result: any = await queryGraph(c, { repoId, commitSHA: sha, operation: 'find_symbol', symbol: 'caller' });
    assert.ok(result.results.length); assert.equal(result.results[0].sourceFile, 'app.py');
    await symlink('/etc/passwd', join(root, 'escape.py'));
    git('add', 'escape.py'); git('commit', '-qm', 'symlink');
    await assert.rejects(extractRepository({ repoId, repositoryPath: root, commitSHA: git('rev-parse', 'HEAD') }), /Symlinks/);
  } finally { await cleanup(c, [repoId]); await c.close(); await rm(root, { recursive: true, force: true }); }
});

test('DEF-040: loadSnapshot transaction timeout is configurable with size-based default', { skip: !enabled }, async () => {
  const c = connectNeo4j();
  const repo = `def040-test-${randomUUID()}`;
  const customRepo = `def040-custom-${randomUUID()}`;
  const envRepo = `def040-env-${randomUUID()}`;
  const input = fixture(repo);
  const originalSession = c.driver.session.bind(c.driver);
  let capturedTimeout: number | undefined;
  const interceptConn = { ...c, driver: { session: (options: any) => {
    const session = originalSession(options);
    return {
      close: () => session.close(),
      executeWrite: (work: any, config: any) => {
        capturedTimeout = config?.timeout;
        return session.executeWrite(work, config);
      },
    };
  } } } as unknown as Neo4jConnection;
  try {
    await initializeSchema(c);
    // 1. Default size-based timeout (fixture has 2 nodes + 1 edge = 3 elements -> min 60,000 ms)
    await loadSnapshot(interceptConn, input);
    assert.equal(capturedTimeout, 60_000);

    // 2. Explicit options.timeoutMs
    await loadSnapshot(interceptConn, fixture(customRepo), { timeoutMs: 95_000 });
    assert.equal(capturedTimeout, 95_000);

    // 3. INGESTION_TX_TIMEOUT_MS environment variable
    const prevEnv = process.env.INGESTION_TX_TIMEOUT_MS;
    try {
      process.env.INGESTION_TX_TIMEOUT_MS = '120000';
      await loadSnapshot(interceptConn, fixture(envRepo));
      assert.equal(capturedTimeout, 120_000);
    } finally {
      if (prevEnv === undefined) delete process.env.INGESTION_TX_TIMEOUT_MS;
      else process.env.INGESTION_TX_TIMEOUT_MS = prevEnv;
    }
  } finally {
    await cleanup(c, [repo, customRepo, envRepo]);
    await c.close();
  }
});

