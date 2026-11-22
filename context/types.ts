export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  sourceFile: string;
  sourceLocation: string;
  community?: string;
  nativeOrder?: number;
  nativePropertiesJson?: string;
}
export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  confidence: string;
  sourceFile: string;
  sourceLocation: string;
  context?: string;
  nativeOrder?: number;
  nativePropertiesJson?: string;
}
export interface RepositorySnapshot {
  repoId: string;
  commitSHA: string;
  commitTimestamp: string;
  repositoryPath: string;
  graphifyVersion: string;
  extractMode?: string;
  artifactHash?: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}
export function requiredText(value: unknown, name: string, max = 1024): string {
  if (typeof value !== 'string' || !value.trim() || value.length > max || /[\x00-\x1f]/.test(value)) {
    throw new Error(`${name} must be nonempty text (at most ${max} characters)`);
  }
  return value;
}
export function commitSHA(value: unknown): string {
  const sha = requiredText(value, 'commitSHA', 64);
  if (!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(sha)) throw new Error('commitSHA must be a full lowercase Git object ID');
  return sha;
}
export function snapshotId(repoId: string, sha: string): string {
  return JSON.stringify([requiredText(repoId, 'repoId', 256), commitSHA(sha)]);
}
