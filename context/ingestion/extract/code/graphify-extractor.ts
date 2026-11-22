import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, readdir, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { commitSHA, requiredText, type RepositorySnapshot } from '../../../types.ts';
import { normalizeGraph } from '../../load/validate-snapshot.ts';

const exec = promisify(execFile);
const GRAPHIFY_VERSION = '0.9.51';

export async function run(file: string, args: string[], cwd: string, signal: AbortSignal): Promise<string> {
  const result = await exec(file, args, { cwd, signal, encoding: 'utf8', maxBuffer: 1024 * 1024 });
  return result.stdout;
}

export async function rejectSymlinks(root: string): Promise<void> {
  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (entry.name === '.git') continue;
    if (entry.isSymbolicLink()) throw new Error('Symlinks are not supported in ingestion snapshots');
    if (entry.isDirectory()) await rejectSymlinks(join(root, entry.name));
  }
}

export interface ExtractRepositoryOptions {
  python?: string;
  graphify?: string;
  signal?: AbortSignal;
  cloneTimeoutMs?: number;
  graphifyTimeoutMs?: number;
}

/** Operator-only API: an existing local Git repository and its exact commit. */
export async function extractRepository(input: {
  repoId: string; repositoryPath: string; commitSHA: string;
}, options: ExtractRepositoryOptions = {}): Promise<RepositorySnapshot> {
  const repoId = requiredText(input.repoId, 'repoId', 256);
  const sha = commitSHA(input.commitSHA);
  const source = resolve(input.repositoryPath);
  const python = options.python ?? process.env.GRAPHIFY_PYTHON ?? 'python3';
  const graphify = options.graphify ?? process.env.GRAPHIFY_BIN
    ?? (python.includes('/') ? join(dirname(resolve(python)), 'graphify') : 'graphify');
  const work = await mkdtemp(join(tmpdir(), 'taffee-ingestion-'));
  const cloneTimeoutMs = options.cloneTimeoutMs
    ?? (process.env.INGESTION_CLONE_TIMEOUT_MS ? parseInt(process.env.INGESTION_CLONE_TIMEOUT_MS, 10) : 120_000);
  const graphifyTimeoutMs = options.graphifyTimeoutMs
    ?? (process.env.INGESTION_GRAPHIFY_TIMEOUT_MS ? parseInt(process.env.INGESTION_GRAPHIFY_TIMEOUT_MS, 10) : 120_000);
  const cloneSignal = options.signal
    ? AbortSignal.any([options.signal, AbortSignal.timeout(cloneTimeoutMs)])
    : AbortSignal.timeout(cloneTimeoutMs);
  const graphifySignal = options.signal
    ? AbortSignal.any([options.signal, AbortSignal.timeout(graphifyTimeoutMs)])
    : AbortSignal.timeout(graphifyTimeoutMs);
  const checkout = join(work, 'source');
  try {
    const version = (await run(python, ['-c', 'import importlib.metadata; print(importlib.metadata.version("graphifyy"))'], work, cloneSignal)).trim();
    if (version !== GRAPHIFY_VERSION) throw new Error(`Expected graphifyy ${GRAPHIFY_VERSION}, found ${version}`);
    try {
      await run('git', ['config', '--global', '--add', 'safe.directory', '*'], work, cloneSignal).catch(() => {});
      await run('git', ['init', checkout], work, cloneSignal);
      await run('git', ['remote', 'add', 'origin', source], checkout, cloneSignal);
      try {
        await run('git', ['fetch', '--depth', '1', 'origin', sha], checkout, cloneSignal);
      } catch {
        await run('git', ['fetch', 'origin', sha], checkout, cloneSignal);
      }
      await run('git', ['-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', sha], checkout, cloneSignal);
    } catch {
      await rm(checkout, { recursive: true, force: true });
      await run('git', ['clone', '--no-local', '--no-checkout', '--', source, checkout], work, cloneSignal);
      await run('git', ['-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', sha], checkout, cloneSignal);
    }
    const git = (args: string[]) => run('git', args, checkout, cloneSignal);
    const actual = (await git(['rev-parse', 'HEAD'])).trim();
    if (actual !== sha) throw new Error('Checkout does not match requested commit');
    if (/^160000 /m.test(await git(['ls-tree', '-r', 'HEAD']))) throw new Error('Submodules require separate ingestion');
    await rejectSymlinks(checkout);
    const timestamp = new Date((await git(['show', '-s', '--format=%cI', 'HEAD'])).trim()).toISOString();

    // The low-level graphify.extract API omits some referenced nodes. Use the
    // native clustered CLI output that was validated in the source project.
    await run(graphify, ['extract', checkout, '--code-only', '--no-viz', '--out', work], work, graphifySignal);
    const output = join(work, 'graphify-out', 'graph.json');
    if ((await stat(output)).size > 32 * 1024 * 1024) throw new Error('Graphify output exceeds 32 MiB');
    const artifact = await readFile(output);
    const raw = JSON.parse(artifact.toString('utf8'));
    return { repoId, commitSHA: sha, commitTimestamp: timestamp, repositoryPath: source,
      graphifyVersion: version, extractMode: 'code-only, clustered',
      artifactHash: createHash('sha256').update(artifact).digest('hex'), ...normalizeGraph(raw) };
  } finally {
    await rm(work, { recursive: true, force: true });
  }
}
