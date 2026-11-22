// Storage contract. Each graph database provider implements GraphStore; nothing outside context/storage imports a driver.
// Invariants (see docs/design/005_storage_interface/SPEC.md): published snapshots are immutable, staged data is never
// read, every read is scoped to one snapshot, reads never write, and a snapshot becomes visible only at publish.

export type SnapshotId = string;

export interface SnapshotRef { repoId: string; commitSHA: string }

export interface StructuralNode { localId: string; label: string; kind: string; sourceFile: string; sourceLocation: string; community: number | null }
export interface StructuralEdge { source: string; target: string; relation: string; confidence: string; sourceFile: string; sourceLocation: string }

export interface SnapshotSummary {
  id: SnapshotId;
  ready: boolean;
  staged: boolean;
  contentHash: string | null;
  artifactHash: string | null;
  declaredNodes: number;
  declaredEdges: number;
  nodes: number;
  edges: number;
  semanticStatus: string | null;
}

export interface ChunkRow {
  id: string;
  file: string;
  startLine: number;
  endLine: number;
  charCount: number;
  embeddedChars: number;
  truncated: boolean;
  text: string;
  vector: number[];
}

export interface ChunkHit { chunkId: string; file: string; startLine: number; endLine: number; score: number; truncated: boolean }

export interface GraphStore {
  /** Create constraints and indexes. Idempotent. */
  initialize(): Promise<void>;

  /** Write a snapshot's graph as staged (hidden from reads). Returns "created", or "unchanged" for an identical snapshot. Throws on a conflicting one. */
  stageSnapshot(snapshot: SnapshotRef & { contentHash: string; artifactHash: string; nodes: StructuralNode[]; edges: StructuralEdge[]; metadata: Record<string, unknown> }): Promise<"created" | "unchanged">;

  /** Make a staged snapshot visible. Idempotent. */
  publishSnapshot(ref: SnapshotRef): Promise<void>;

  summary(ref: SnapshotRef): Promise<SnapshotSummary | null>;

  /** Write chunks, vectors and links for a snapshot in one transaction. */
  writeSemanticLayer(ref: SnapshotRef, chunks: ChunkRow[], links: { chunkId: string; localId: string }[], meta: Record<string, unknown>): Promise<void>;

  /** Ready repos, optionally filtered by name. */
  listRepos(filter: { query?: string; limit: number; offset: number }): Promise<{ repoId: string; commitSHA: string; semanticStatus: string | null }[]>;

  /** Newest ready snapshot for a repo, or the one matching a commit prefix. */
  resolveSnapshot(repoId: string, commitPrefix?: string): Promise<SnapshotRef | null>;

  /** All nodes and edges of one snapshot. */
  readGraph(ref: SnapshotRef): Promise<{ nodes: StructuralNode[]; edges: StructuralEdge[] }>;

  /** Vector search within one snapshot. */
  searchChunks(ref: SnapshotRef, vector: number[], topK: number): Promise<ChunkHit[]>;

  close(): Promise<void>;
}
