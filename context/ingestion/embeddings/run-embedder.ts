import { spawn } from 'node:child_process';
import { mkdtemp, open, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SEMANTIC_CONFIG, type SemanticConfig } from '../chunks/chunker.ts';

export interface EmbedItem { id: string; text: string }
export interface EmbeddingRow { id: string; embedding: number[]; tokens?: number; tokenTruncated?: boolean }
export interface EmbedderMeta {
  model: string; modelRevision: string; codeRevision: string; dimension: number; count: number;
  loadSeconds: number; embedSeconds: number; torch: string; transformers: string; peakRssMb: number;
}
/** Embeds items and hands validated rows to onRows in batches; rows already delivered stay delivered if the run fails. */
export type Embed = (items: EmbedItem[], onRows: (rows: EmbeddingRow[]) => Promise<void>, signal?: AbortSignal) => Promise<EmbedderMeta | undefined>;

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), 'embed_chunks.py');
const MAX_OUTPUT_BYTES = 256 * 1024 * 1024;
const BATCH_ROWS = 100;

export function validateEmbedding(row: unknown, dimension: number): EmbeddingRow {
  const value = row as { id?: unknown; embedding?: unknown; tokens?: unknown; tokenTruncated?: unknown } | null;
  if (!value || typeof value.id !== 'string' || !Array.isArray(value.embedding)) throw new Error('Malformed embedding row');
  if (value.embedding.length !== dimension) throw new Error(`Embedding dimension ${value.embedding.length}, expected ${dimension}`);
  if (!value.embedding.every(x => typeof x === 'number' && Number.isFinite(x))) throw new Error('Embedding contains a non-finite number');
  if (value.tokens !== undefined && (typeof value.tokens !== 'number' || !Number.isSafeInteger(value.tokens) || value.tokens < 0)) throw new Error('Malformed embedding token count');
  if (value.tokenTruncated !== undefined && typeof value.tokenTruncated !== 'boolean') throw new Error('Malformed embedding truncation flag');
  return { id: value.id, embedding: value.embedding as number[],
    ...(value.tokens === undefined ? {} : { tokens: value.tokens as number }),
    ...(value.tokenTruncated === undefined ? {} : { tokenTruncated: value.tokenTruncated as boolean }) };
}

/** Incrementally reads a growing JSON Lines embeddings file and validates every row. Output is ASCII (json.dumps default). */
export class EmbeddingReader {
  private offset = 0;
  private rest = '';
  private readonly seen = new Set<string>();
  private batch: EmbeddingRow[] = [];
  constructor(private readonly file: string, private readonly expectedIds: Set<string>, private readonly dimension: number,
    private readonly onRows: (rows: EmbeddingRow[]) => Promise<void>) {}
  get count(): number { return this.seen.size; }
  private async flush(): Promise<void> {
    if (!this.batch.length) return;
    const rows = this.batch;
    this.batch = [];
    await this.onRows(rows);
  }
  private async accept(line: string): Promise<void> {
    const row = validateEmbedding(JSON.parse(line), this.dimension);
    if (!this.expectedIds.has(row.id)) throw new Error('Embedding for an unrequested chunk');
    if (this.seen.has(row.id)) throw new Error('Duplicate embedding for a chunk');
    this.seen.add(row.id);
    this.batch.push(row);
    if (this.batch.length >= BATCH_ROWS) await this.flush();
  }
  /** Consumes newly appended complete lines. With final, the unterminated last line is consumed too; a cut-off one is tolerated only with allowPartial. */
  async drain(options: { final: boolean; allowPartial: boolean; minBatch: number }): Promise<void> {
    const size = (await stat(this.file)).size;
    if (size > MAX_OUTPUT_BYTES) throw new Error('Embeddings output exceeds size bound');
    if (size > this.offset) {
      const handle = await open(this.file, 'r');
      try {
        const buffer = Buffer.alloc(size - this.offset);
        await handle.read(buffer, 0, buffer.length, this.offset);
        this.offset = size;
        this.rest += buffer.toString('utf8');
      } finally { await handle.close(); }
    }
    const lines = this.rest.split('\n');
    this.rest = lines.pop() ?? '';
    for (const line of lines) if (line) await this.accept(line);
    if (options.final && this.rest) {
      const last = this.rest;
      this.rest = '';
      try { JSON.parse(last); }
      catch (error) {
        if (options.allowPartial) { await this.flush(); return; }
        throw error;
      }
      await this.accept(last);
    }
    if (options.final || this.batch.length >= options.minBatch) await this.flush();
  }
}

/** Reads a finished JSON Lines embeddings file, validating every row. A cut-off last line is tolerated only when allowPartial is set. */
export async function readEmbeddingRows(file: string, expectedIds: Set<string>, dimension: number,
  options: { allowPartial: boolean }, onRows: (rows: EmbeddingRow[]) => Promise<void>): Promise<number> {
  const reader = new EmbeddingReader(file, expectedIds, dimension, onRows);
  await reader.drain({ final: true, allowPartial: options.allowPartial, minBatch: BATCH_ROWS });
  if (!options.allowPartial && reader.count !== expectedIds.size) {
    throw new Error(`Embedding count mismatch: expected ${expectedIds.size}, got ${reader.count}`);
  }
  return reader.count;
}

export function pythonEmbedder(options: { python?: string; config?: SemanticConfig; timeoutMs?: number; saveIntervalMs?: number; segmentSize?: number } = {}): Embed {
  const runOnce: Embed = async (items, onRows, signal) => {
    const config = options.config ?? SEMANTIC_CONFIG;
    const python = options.python ?? process.env.EMBED_PYTHON ?? process.env.GRAPHIFY_PYTHON ?? 'python3';
    const dir = await mkdtemp(join(tmpdir(), 'taffee-embed-'));
    const files = { src: join(dir, 'in.jsonl'), out: join(dir, 'out.jsonl'), meta: join(dir, 'meta.json') };
    try {
      await writeFile(files.src, items.map(i => JSON.stringify(i)).join('\n') + '\n', { mode: 0o600 });
      await writeFile(files.out, '', { mode: 0o600 });
      const timeout = AbortSignal.timeout(options.timeoutMs ?? (Number(process.env.EMBED_TIMEOUT_MS) || 120 * 60_000));
      const args = [SCRIPT, '--in', files.src, '--out', files.out, '--meta', files.meta, '--model', config.model,
        '--model-revision', config.modelRevision, '--code-revision', config.codeRevision,
        '--dimension', String(config.dimension), '--max-chars', String(config.maxEmbedChars), '--max-tokens', String(config.maxEmbedTokens),
        '--threads', process.env.TORCH_THREADS ?? '2'];
      const total = items.length;
      const reader = new EmbeddingReader(files.out, new Set(items.map(i => i.id)), config.dimension, onRows);
      // Rows are saved while the model runs, so a host freeze or reset loses at most one interval of work.
      const stop = new AbortController();
      let progress: Promise<void> = Promise.resolve();
      let progressError: unknown;
      const timer = setInterval(() => {
        progress = progress.then(() => reader.drain({ final: false, allowPartial: true, minBatch: 1 }))
          .catch(error => { progressError ??= error; stop.abort(); });
      }, options.saveIntervalMs ?? 15_000);
      const signals = [timeout, stop.signal, ...(signal ? [signal] : [])];
      let failure: string | null;
      try {
        failure = await new Promise<string | null>(resolve => {
          const child = spawn(python, args, { env: { ...process.env, HF_HUB_OFFLINE: '1', TRANSFORMERS_OFFLINE: '1' }, stdio: ['ignore', 'ignore', 'pipe'], signal: AbortSignal.any(signals) });
          let tail = '';
          child.stderr.on('data', (chunk: Buffer) => { process.stderr.write(chunk); tail = (tail + chunk.toString()).slice(-2000); });
          child.on('error', error => resolve(`Embedder failed to run: ${error.message}`));
          child.on('close', code => resolve(code === 0 ? null : `Embedder exited with code ${code}: ${tail.trim().split('\n').slice(-3).join(' | ')}`));
        });
      } finally { clearInterval(timer); }
      await progress;
      if (progressError) throw progressError;
      await reader.drain({ final: true, allowPartial: failure !== null, minBatch: 1 });
      if (failure) throw new Error(failure);
      if (reader.count !== total) throw new Error(`Embedding count mismatch: expected ${total}, got ${reader.count}`);
      return JSON.parse(await readFile(files.meta, 'utf8')) as EmbedderMeta;
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  };
  // A fresh process per segment bounds resident memory: a long single run grew until it was killed on a 2 GB cap.
  const segmentSize = options.segmentSize ?? (Number(process.env.EMBED_SEGMENT) || 100);
  return async (items, onRows, signal) => {
    let meta: EmbedderMeta | undefined;
    for (let i = 0; i < items.length; i += segmentSize) {
      const part = await runOnce(items.slice(i, i + segmentSize), onRows, signal);
      if (part) meta = meta ? { ...part, count: meta.count + part.count, loadSeconds: meta.loadSeconds + part.loadSeconds,
        embedSeconds: meta.embedSeconds + part.embedSeconds, peakRssMb: Math.max(meta.peakRssMb, part.peakRssMb) } : part;
    }
    return meta;
  };
}
