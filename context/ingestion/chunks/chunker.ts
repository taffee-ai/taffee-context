import { createHash } from 'node:crypto';

export interface SemanticConfig {
  model: string;
  modelRevision: string;
  codeRevision: string;
  dimension: number;
  chunkLines: number;
  maxChunkChars: number;
  maxEmbedChars: number;
  maxEmbedTokens: number;
  extensions: string[];
}
// Immutable Hugging Face commit hashes for pinned model weights and tokenizer code.
export const SEMANTIC_CONFIG: SemanticConfig = {
  model: 'jinaai/jina-embeddings-v2-base-code',
  modelRevision: '516f4baf13dec4ddddda8631e019b5737c8bc250',
  codeRevision: '3baf9e3ac750e76e8edd3019170176884695fb94',
  dimension: 768,
  chunkLines: 150,
  maxChunkChars: 6000,
  maxEmbedChars: 8000,
  maxEmbedTokens: 8192,
  extensions: ['.c', '.cc', '.cpp', '.go', '.h', '.hpp', '.java', '.js', '.jsx', '.py', '.rb', '.rs', '.ts', '.tsx'],
};
export const MODEL_MAX_TOKENS = 8192;
export const SEMANTIC_LIMITS = { maxFiles: 5000, maxFileBytes: 1024 * 1024, maxChunks: 20000 };

export interface SourceFile { path: string; text: string }
export interface Chunk {
  id: string;
  file: string;
  startLine: number;
  endLine: number;
  charCount: number;
  embeddedChars: number;
  truncated: boolean;
  text: string;
}
export interface ChunkEntity { localId: string; sourceFile: string; sourceLocation: string }
export interface ChunkLink { chunkId: string; localId: string }

const compare = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;

export function chunkId(snapshot: string, file: string, startLine: number): string {
  return `${snapshot}::chunk::${file}::${startLine}`;
}
export function isChunkable(path: string, config: SemanticConfig = SEMANTIC_CONFIG): boolean {
  const parts = path.split('/');
  const name = parts[parts.length - 1];
  return config.extensions.some(ext => name.endsWith(ext)) && !name.includes('.min.') && !parts.includes('node_modules');
}
function splitLines(text: string): string[] {
  const lines = text.split(/\r\n|\r|\n/);
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  return lines;
}
function cut(text: string, max: number): string {
  if (text.length <= max) return text;
  const code = text.charCodeAt(max - 1);
  return text.slice(0, code >= 0xd800 && code <= 0xdbff ? max - 1 : max);
}
export function chunkSource(snapshot: string, files: SourceFile[], config: SemanticConfig = SEMANTIC_CONFIG,
  limits = SEMANTIC_LIMITS): Chunk[] {
  const chunks: Chunk[] = [];
  for (const file of files.filter(f => isChunkable(f.path, config)).sort((a, b) => compare(a.path, b.path))) {
    const lines = splitLines(file.text);
    // Whole lines, closing a chunk before it exceeds maxChunkChars (or chunkLines). A single line over the budget
    // forms its own chunk and is cut at maxEmbedChars, which is recorded as truncated.
    let i = 0;
    while (i < lines.length) {
      let end = i;
      let chars = 0;
      while (end < lines.length && end - i < config.chunkLines) {
        const added = lines[end].length + (end > i ? 1 : 0);
        if (end > i && chars + added > config.maxChunkChars) break;
        chars += added;
        end++;
      }
      const text = lines.slice(i, end).join('\n');
      if (text.trim()) {
        const embedded = cut(text, config.maxEmbedChars);
        chunks.push({ id: chunkId(snapshot, file.path, i + 1), file: file.path, startLine: i + 1, endLine: end,
          charCount: text.length, embeddedChars: embedded.length, truncated: text.length > embedded.length, text: embedded });
        if (chunks.length > limits.maxChunks) throw new Error(`Chunk count exceeds ${limits.maxChunks}`);
      }
      i = end;
    }
  }
  return chunks;
}
function startLine(location: string): number | null {
  const match = /^L(\d+)$/.exec(location);
  const line = match ? Number(match[1]) : NaN;
  return Number.isSafeInteger(line) && line >= 1 ? line : null;
}
// Link by exact file and start-line containment only; never by name.
export function computeLinks(chunks: Chunk[], entities: ChunkEntity[]): ChunkLink[] {
  const byFile = new Map<string, { localId: string; line: number }[]>();
  for (const entity of entities) {
    const line = startLine(entity.sourceLocation);
    if (line === null || !entity.sourceFile) continue;
    const list = byFile.get(entity.sourceFile) ?? [];
    list.push({ localId: entity.localId, line });
    byFile.set(entity.sourceFile, list);
  }
  const links: ChunkLink[] = [];
  for (const chunk of chunks) {
    for (const entity of byFile.get(chunk.file) ?? []) {
      if (entity.line >= chunk.startLine && entity.line <= chunk.endLine) links.push({ chunkId: chunk.id, localId: entity.localId });
    }
  }
  return links.sort((a, b) => compare(a.chunkId, b.chunkId) || compare(a.localId, b.localId));
}
function sha256(value: unknown): string {
  return createHash('sha256').update(JSON.stringify(value)).digest('hex');
}
// The token cap joins the hash only when it differs from the model maximum, so snapshots built before the cap existed stay valid.
export function semanticConfigHash(config: SemanticConfig): string {
  const parts: unknown[] = [config.model, config.modelRevision, config.codeRevision, config.dimension,
    config.chunkLines, config.maxEmbedChars, config.maxChunkChars, [...config.extensions].sort()];
  if (config.maxEmbedTokens !== MODEL_MAX_TOKENS) parts.push(config.maxEmbedTokens);
  return sha256(parts);
}
/** Operational config: EMBED_MAX_TOKENS lowers the per-chunk token cap to bound memory; it is recorded as part of the config. */
export function configFromEnv(env: NodeJS.ProcessEnv = process.env): SemanticConfig {
  const raw = env.EMBED_MAX_TOKENS;
  if (raw === undefined || raw === '') return SEMANTIC_CONFIG;
  const cap = Number(raw);
  if (!Number.isInteger(cap) || cap < 128 || cap > MODEL_MAX_TOKENS) throw new Error(`EMBED_MAX_TOKENS must be an integer from 128 to ${MODEL_MAX_TOKENS}`);
  return { ...SEMANTIC_CONFIG, maxEmbedTokens: cap };
}
// Covers config, chunk layout and links; vectors are excluded because float output is not guaranteed bit-identical.
export function semanticContentHash(config: SemanticConfig, chunks: Chunk[], links: ChunkLink[]): string {
  return sha256([semanticConfigHash(config),
    chunks.map(c => [c.id, c.file, c.startLine, c.endLine, c.charCount, c.embeddedChars, c.truncated]).sort((a, b) => compare(String(a[0]), String(b[0]))),
    links.map(l => [l.chunkId, l.localId])]);
}
export type SemanticStart = 'new' | 'resume' | 'unchanged' | 'restart';
export function decideSemanticStart(existing: { status: string | null; configHash: string | null; contentHash: string | null },
  configHash: string, contentHash: string): SemanticStart {
  if (!existing.status) return 'new';
  if (existing.configHash !== configHash) {
    // An incomplete layer carries no links and is not searchable, so it may restart under a new config; a complete one is immutable.
    if (existing.status === 'building') return 'restart';
    throw new Error('Immutable semantic config conflict: model or chunking parameters differ');
  }
  if (existing.contentHash !== contentHash) throw new Error('Immutable semantic content conflict: chunk layout or links differ');
  return existing.status === 'ready' ? 'unchanged' : 'resume';
}
