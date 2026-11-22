import { test } from 'node:test';
import assert from 'node:assert/strict';
import { graphHash, normalizeGraph, validateSnapshot } from '../ingestion/load/validate-snapshot.ts';
import { validateQuery } from '../retrieval/query/neo4j-query.ts';
import { snapshotId, type RepositorySnapshot } from '../types.ts';

export function fixture(repoId = 'fixture'): RepositorySnapshot {
  return { repoId, commitSHA: 'a'.repeat(40), commitTimestamp: '2026-01-01T00:00:00.000Z',
    repositoryPath: '/fixture', graphifyVersion: '0.9.51', nodes: [
      { id: 'caller', label: 'caller', kind: 'function', sourceFile: 'src/app.ts', sourceLocation: 'L1' },
      { id: 'callee', label: 'callee', kind: 'function', sourceFile: 'src/app.ts', sourceLocation: 'L3' },
    ], edges: [{ source: 'caller', target: 'callee', relation: 'calls', confidence: 'EXTRACTED', sourceFile: 'src/app.ts', sourceLocation: 'L2' }] };
}
test('snapshot validation rejects malformed identity, duplicate IDs, dangling edges and escaping sources', () => {
  assert.throws(() => snapshotId('repo', 'main'), /full lowercase/);
  const graph = fixture();
  assert.throws(() => normalizeGraph({ ...graph, nodes: [graph.nodes[0], graph.nodes[0]] }), /Duplicate/);
  assert.throws(() => normalizeGraph({ ...graph, edges: [{ ...graph.edges[0], target: 'missing' }] }), /Dangling/);
  assert.throws(() => normalizeGraph({ ...graph, nodes: [{ ...graph.nodes[0], sourceFile: '../secret' }] }), /relative/);
});
test('hash is order-independent after normalization and independent of checkout location', () => {
  const a = validateSnapshot(fixture());
  const b = validateSnapshot({ ...fixture(), repositoryPath: '/other', nodes: [...fixture().nodes].reverse() });
  assert.equal(graphHash(a), graphHash(b));
  assert.notEqual(graphHash(a), graphHash({ ...a, graphifyVersion: 'other' }));
});
test('query rejects arbitrary Cypher, invalid limits and unsupported operations', () => {
  assert.throws(() => validateQuery({ repoId: 'r', operation: 'resolve', cypher: 'DELETE' }), /Unknown/);
  assert.throws(() => validateQuery({ repoId: 'r', operation: 'resolve', limit: 1000 }), /limit/);
  assert.throws(() => validateQuery({ repoId: 'r', operation: 'delete' }), /Unsupported/);
});
test('native Graphify links retain direction, duplicate edges, community and evidence', () => {
  const graph = normalizeGraph({ nodes: [
    { id: 'a', label: 'A', community: 2, source_file: 'src/a.py', source_location: 'L1' },
    { id: 'b', label: 'B', source_file: 'src/b.py', source_location: 'L2' },
  ], links: [
    { source: 'a', target: 'b', relation: 'calls', context: 'call', source_file: 'src/a.py', source_location: 'L3' },
    { source: 'a', target: 'b', relation: 'calls', context: 'call', source_file: 'src/a.py', source_location: 'L4' },
  ] });
  assert.equal(graph.nodes[0].community, '2');
  assert.equal(graph.edges.length, 2);
  assert.equal(graph.edges[0].source, 'a');
  assert.equal(graph.edges[0].target, 'b');
  assert.ok(graph.edges[0].nativePropertiesJson?.includes('source_file'));
  assert.deepEqual(normalizeGraph(graph), graph);
});
