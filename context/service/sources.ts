import { execFile } from 'node:child_process';
import { mkdir, realpath, rm } from 'node:fs/promises';
import { sep } from 'node:path';
import { promisify } from 'node:util';

const run = promisify(execFile);
const SHA = /^[0-9a-f]{40}$/;
const RELEASE = /^refs\/tags\/v?(\d+)\.(\d+)\.(\d+)$/;

async function git(args: string[], cwd?: string): Promise<string> {
  // The service may run as a different user from the repo owner; trust only the folder git is pointed at.
  const scoped = cwd ? ['-c', `safe.directory=${cwd}`, ...args] : args;
  const { stdout } = await run('git', scoped, { cwd, env: { ...process.env, GIT_TERMINAL_PROMPT: '0' }, maxBuffer: 16 * 1024 * 1024 });
  return stdout.trim();
}

function compareVersions(a: number[], b: number[]): number {
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}

export const isUrlSource = (source: string): boolean => /^(https:\/\/|ssh:\/\/|git@)/.test(source);
export const isAllowedUrl = (source: string, allowlist: string[]): boolean => allowlist.some(prefix => source.startsWith(prefix));

/** Resolves a branch, tag or full SHA on a remote to a commit. Without a ref, picks the highest vMAJOR.MINOR.PATCH tag. */
export async function resolveUrl(source: string, ref: string | undefined): Promise<string> {
  if (ref && SHA.test(ref)) return ref;
  const refs = new Map<string, string>();
  for (const line of (await git(['ls-remote', source])).split('\n').filter(Boolean)) {
    const [sha, name] = line.split('\t');
    if (name.endsWith('^{}')) refs.set(name.slice(0, -3), sha); // peeled annotated tag: the commit itself
    else if (!refs.has(name)) refs.set(name, sha);
  }
  if (ref) {
    const found = refs.get(`refs/tags/${ref}`) ?? refs.get(`refs/heads/${ref}`);
    if (!found) throw new Error(`ref '${ref}' not found in ${source}`);
    return found;
  }
  let best: { sha: string; v: [number, number, number] } | null = null;
  for (const [name, sha] of refs) {
    const m = RELEASE.exec(name);
    if (!m) continue;
    const v: [number, number, number] = [Number(m[1]), Number(m[2]), Number(m[3])];
    if (!best || compareVersions(v, best.v) > 0) best = { sha, v };
  }
  if (!best) throw new Error('no release tag (vMAJOR.MINOR.PATCH) found; pass --ref');
  return best.sha;
}

/** Fetches exactly one commit into dest. */
export async function fetchUrl(source: string, sha: string, dest: string): Promise<void> {
  await rm(dest, { recursive: true, force: true });
  await mkdir(dest, { recursive: true });
  await git(['init', '-q'], dest);
  await git(['fetch', '--depth', '1', source, sha], dest);
  await git(['checkout', '-q', '--detach', 'FETCH_HEAD'], dest);
}

/** Accepts a local folder only under the configured root, with a clean working tree. Returns its HEAD commit. */
export async function resolveLocal(input: string, root: string): Promise<{ repositoryPath: string; sha: string }> {
  const real = await realpath(input);
  const realRoot = await realpath(root);
  if (!real.startsWith(realRoot + sep)) throw new Error('local path must be inside INGEST_LOCAL_ROOT');
  if (await git(['status', '--porcelain'], real)) throw new Error('working tree has uncommitted changes');
  return { repositoryPath: real, sha: await git(['rev-parse', 'HEAD'], real) };
}
