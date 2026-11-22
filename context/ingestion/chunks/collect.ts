import { mkdtemp, readFile, readdir, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { commitSHA } from '../../types.ts';
import { rejectSymlinks, run } from '../extract/code/graphify-extractor.ts';
import { SEMANTIC_CONFIG, SEMANTIC_LIMITS, isChunkable, type SemanticConfig, type SourceFile } from './chunker.ts';

async function walk(root: string, dir: string, config: SemanticConfig, limits: typeof SEMANTIC_LIMITS, out: SourceFile[]): Promise<void> {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === '.git' || entry.name === 'node_modules') continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) { await walk(root, full, config, limits, out); continue; }
    const path = full.slice(root.length + 1).split('\\').join('/');
    if (!entry.isFile() || !isChunkable(path, config)) continue;
    if (out.length >= limits.maxFiles) throw new Error(`Source file count exceeds ${limits.maxFiles}`);
    if ((await stat(full)).size > limits.maxFileBytes) throw new Error(`Source file ${path} exceeds ${limits.maxFileBytes} bytes`);
    out.push({ path, text: await readFile(full, 'utf8') });
  }
}

/** Reads chunkable files from a temporary checkout of the exact commit, so untracked files are never seen. */
export async function collectSource(input: { repositoryPath: string; commitSHA: string }, options: {
  config?: SemanticConfig; limits?: typeof SEMANTIC_LIMITS; signal?: AbortSignal;
} = {}): Promise<SourceFile[]> {
  const sha = commitSHA(input.commitSHA);
  const source = resolve(input.repositoryPath);
  const config = options.config ?? SEMANTIC_CONFIG;
  const limits = options.limits ?? SEMANTIC_LIMITS;
  const signal = options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(120_000)]) : AbortSignal.timeout(120_000);
  const work = await mkdtemp(join(tmpdir(), 'taffee-chunks-'));
  const checkout = join(work, 'source');
  try {
    await run('git', ['clone', '--no-local', '--no-checkout', '--', source, checkout], work, signal);
    await run('git', ['-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', sha], checkout, signal);
    const git = (args: string[]) => run('git', args, checkout, signal);
    if ((await git(['rev-parse', 'HEAD'])).trim() !== sha) throw new Error('Checkout does not match requested commit');
    if (/^160000 /m.test(await git(['ls-tree', '-r', 'HEAD']))) throw new Error('Submodules require separate ingestion');
    await rejectSymlinks(checkout);
    const files: SourceFile[] = [];
    await walk(checkout, checkout, config, limits, files);
    return files;
  } finally {
    await rm(work, { recursive: true, force: true });
  }
}
