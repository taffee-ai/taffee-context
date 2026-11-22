import { createHash } from 'node:crypto';
import { posix } from 'node:path';
import { requiredText, snapshotId, type GraphEdge, type GraphNode, type RepositorySnapshot } from '../../types.ts';

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Expected graph object');
  return value as Record<string, unknown>;
}
function optionalText(value: unknown, name: string): string {
  return value == null || value === '' ? '' : requiredText(value, name, 4096);
}
function sourceFile(value: unknown): string {
  const path = optionalText(value, 'sourceFile');
  if (path && (posix.isAbsolute(path) || path.includes('\\') || path.split('/').includes('..') || /^[A-Za-z]:/.test(path))) {
    throw new Error('sourceFile must be a repository-relative path');
  }
  return path;
}
function nativeOrder(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error('Invalid native order');
  return value;
}
function artifactHash(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) throw new Error('Invalid artifactHash');
  return value;
}
const compare = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;
export function normalizeGraph(raw: unknown): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const graph = object(raw);
  const native = Array.isArray(graph.links);
  const rawEdges = native ? graph.links : graph.edges;
  if (!Array.isArray(graph.nodes) || !Array.isArray(rawEdges)) throw new Error('Expected nodes and links/edges arrays');
  if (graph.nodes.length > 50_000 || rawEdges.length > 200_000) throw new Error('Snapshot exceeds bounded ingestion capacity');
  const nodes = graph.nodes.map((value, index) => {
    const n = object(value);
    return { id: requiredText(n.id, 'node id'), label: requiredText(n.label ?? n.id, 'label'),
      kind: optionalText(n.kind ?? n.type ?? n.entity_type ?? n.file_type, 'kind'),
      sourceFile: sourceFile(n.sourceFile ?? n.source_file),
      sourceLocation: optionalText(n.sourceLocation ?? n.source_location, 'sourceLocation'),
      ...(n.community == null ? {} : { community: optionalText(String(n.community), 'community') }),
      ...(native ? { nativeOrder: index, nativePropertiesJson: JSON.stringify(n) }
        : { ...(n.nativeOrder === undefined ? {} : { nativeOrder: nativeOrder(n.nativeOrder) }),
          ...(n.nativePropertiesJson === undefined ? {} : { nativePropertiesJson: requiredText(n.nativePropertiesJson, 'nativePropertiesJson', 256_000) }) }) };
  });
  const ids = new Set(nodes.map(n => n.id));
  if (ids.size !== nodes.length) throw new Error('Duplicate node IDs');
  const edges = rawEdges.map((value, index) => {
    const e = object(value);
    const source = requiredText(e.source, 'edge source'), target = requiredText(e.target, 'edge target');
    if (!ids.has(source) || !ids.has(target)) throw new Error('Dangling edge endpoint');
    return { source, target, relation: requiredText(e.relation, 'relation'),
      confidence: optionalText(e.confidence, 'confidence'),
      sourceFile: sourceFile(e.sourceFile ?? e.source_file),
      sourceLocation: optionalText(e.sourceLocation ?? e.source_location, 'sourceLocation'),
      ...(e.context == null ? {} : { context: optionalText(e.context, 'context') }),
      ...(native ? { nativeOrder: index, nativePropertiesJson: JSON.stringify(e) }
        : { ...(e.nativeOrder === undefined ? {} : { nativeOrder: nativeOrder(e.nativeOrder) }),
          ...(e.nativePropertiesJson === undefined ? {} : { nativePropertiesJson: requiredText(e.nativePropertiesJson, 'nativePropertiesJson', 256_000) }) }) };
  });
  return { nodes: nodes.sort((a, b) => compare(a.id, b.id)),
    edges: (native ? edges : [...new Map(edges.map(e => [JSON.stringify(e), e])).values()])
      .sort((a, b) => compare(JSON.stringify(a), JSON.stringify(b))) };
}
export function validateSnapshot(value: RepositorySnapshot): RepositorySnapshot {
  snapshotId(value.repoId, value.commitSHA);
  const timestamp = new Date(requiredText(value.commitTimestamp, 'commitTimestamp'));
  if (!Number.isFinite(timestamp.getTime())) throw new Error('Invalid commitTimestamp');
  return { repoId: value.repoId, commitSHA: value.commitSHA,
    commitTimestamp: timestamp.toISOString(), repositoryPath: requiredText(value.repositoryPath, 'repositoryPath', 4096),
    graphifyVersion: requiredText(value.graphifyVersion, 'graphifyVersion'),
    ...(value.extractMode === undefined ? {} : { extractMode: requiredText(value.extractMode, 'extractMode') }),
    ...(value.artifactHash === undefined ? {} : { artifactHash: artifactHash(value.artifactHash) }),
    ...normalizeGraph(value) };
}
export function graphHash(snapshot: RepositorySnapshot): string {
  // Checkout location is deployment metadata, not part of graph identity.
  const { repositoryPath: _, ...content } = snapshot;
  return createHash('sha256').update(JSON.stringify(content)).digest('hex');
}
