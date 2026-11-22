import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { hashToken, type ServiceConfig } from '../service/config.ts';
import { createIngestServer } from '../service/http.ts';
import { JobQueue } from '../service/queue.ts';
import { isAllowedUrl, resolveLocal } from '../service/sources.ts';
import { parseArgs } from '../service/client.ts';

const SHA1 = 'a'.repeat(40);
const SHA2 = 'b'.repeat(40);
const SHA3 = 'c'.repeat(40);

test('queue: one job per repo and commit; a repeat returns the same job', () => {
  const queue = new JobQueue(':memory:');
  const first = queue.enqueue({ repoId: 'r', source: 'git@x:r.git', sourceKind: 'url', sha: SHA1 });
  const again = queue.enqueue({ repoId: 'r', source: 'git@x:r.git', sourceKind: 'url', sha: SHA1 });
  assert.equal(first.created, true);
  assert.equal(again.created, false);
  assert.equal(again.job.id, first.job.id);
  queue.close();
});

test('queue: same repo never runs two jobs at once; other repos can', () => {
  const queue = new JobQueue(':memory:');
  queue.enqueue({ repoId: 'r', source: 's', sourceKind: 'url', sha: SHA1 });
  queue.enqueue({ repoId: 'r', source: 's', sourceKind: 'url', sha: SHA2 });
  queue.enqueue({ repoId: 'other', source: 's', sourceKind: 'url', sha: SHA3 });
  const a = queue.claim('w1', 60_000);
  assert.equal(a?.sha, SHA1);
  const b = queue.claim('w2', 60_000);
  assert.equal(b?.repoId, 'other', 'second repo runs while the first repo is busy');
  assert.equal(queue.claim('w3', 60_000), null, 'the second commit of the busy repo waits');
  queue.finish(a!.id, 'ready', null);
  assert.equal(queue.claim('w3', 60_000)?.sha, SHA2, 'the waiting commit runs once the repo is free');
  queue.close();
});

test('queue: an expired lease is recovered and the job is claimed again', async () => {
  const queue = new JobQueue(':memory:');
  queue.enqueue({ repoId: 'r', source: 's', sourceKind: 'url', sha: SHA1 });
  const first = queue.claim('dead-worker', 1);
  assert.ok(first);
  await new Promise(resolve => setTimeout(resolve, 10));
  const second = queue.claim('live-worker', 60_000);
  assert.equal(second?.id, first.id);
  assert.equal(second?.attempts, 2);
  queue.close();
});

test('queue: a failed job is queued again when it is requested again', () => {
  const queue = new JobQueue(':memory:');
  const { job } = queue.enqueue({ repoId: 'r', source: 's', sourceKind: 'url', sha: SHA1 });
  queue.claim('w', 60_000);
  queue.finish(job.id, 'failed', 'boom');
  const retry = queue.enqueue({ repoId: 'r', source: 's', sourceKind: 'url', sha: SHA1 });
  assert.equal(retry.job.status, 'queued');
  assert.equal(retry.job.error, null);
  queue.close();
});

test('sources: only allowlisted URL prefixes are accepted', () => {
  const allowlist = ['git@github.com:your-org/'];
  assert.equal(isAllowedUrl('git@github.com:your-org/demo-shop.git', allowlist), true);
  assert.equal(isAllowedUrl('git@github.com:someone-else/repo.git', allowlist), false);
  assert.equal(isAllowedUrl('git@github.com:your-org-evil/repo.git', allowlist), false, 'prefix must end at the slash');
});

test('sources: a local path outside the configured root is refused', async () => {
  const base = await mkdtemp(join(tmpdir(), 'ingest-root-'));
  try {
    const root = join(base, 'root');
    const outside = join(base, 'outside');
    await mkdir(root); await mkdir(outside);
    execFileSync('git', ['init', '-q'], { cwd: outside });
    execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x'], { cwd: outside });
    await assert.rejects(resolveLocal(outside, root), /inside INGEST_LOCAL_ROOT/);
  } finally { await rm(base, { recursive: true, force: true }); }
});

test('sources: a local repo with uncommitted changes is refused', async () => {
  const base = await mkdtemp(join(tmpdir(), 'ingest-dirty-'));
  try {
    const repo = join(base, 'repo');
    await mkdir(repo);
    execFileSync('git', ['init', '-q'], { cwd: repo });
    execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x'], { cwd: repo });
    await writeFile(join(repo, 'dirty.txt'), 'x');
    await assert.rejects(resolveLocal(repo, base), /uncommitted changes/);
  } finally { await rm(base, { recursive: true, force: true }); }
});

const config = (): ServiceConfig => ({
  port: 0, adminTokenHash: hashToken('admin-secret'), sourceAllowlist: [], localRoot: null,
  workers: 1, queueFile: ':memory:', workspace: '/tmp/unused', leaseMs: 60_000,
});

test('http: health is open; jobs require the admin token', async () => {
  const queue = new JobQueue(':memory:');
  const server = createIngestServer(config(), queue);
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', () => resolve()));
  const base = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
  try {
    assert.equal((await fetch(`${base}/healthz`)).status, 200);
    assert.equal((await fetch(`${base}/jobs/00000000-0000-0000-0000-000000000000`)).status, 401);
    const wrong = await fetch(`${base}/jobs/00000000-0000-0000-0000-000000000000`, { headers: { authorization: 'Bearer nope' } });
    assert.equal(wrong.status, 401);
    const right = await fetch(`${base}/jobs/00000000-0000-0000-0000-000000000000`, { headers: { authorization: 'Bearer admin-secret' } });
    assert.equal(right.status, 404);
  } finally {
    await new Promise(resolve => server.close(resolve));
    queue.close();
  }
});

test('taffee-ingest: submit and status parse; bad input is refused with usage', () => {
  assert.deepEqual(parseArgs(['--submit', '--type', 'code', '--id', 'r1', '--source', 'git@x:r.git']),
    { kind: 'submit', type: 'code', id: 'r1', source: 'git@x:r.git' });
  assert.deepEqual(parseArgs(['--submit', '--type', 'code', '--id', 'r1', '--source', '/srv/r', '--ref', 'v1.2.0']),
    { kind: 'submit', type: 'code', id: 'r1', source: '/srv/r', ref: 'v1.2.0' });
  assert.deepEqual(parseArgs(['--status', 'j_1']), { kind: 'status', jobId: 'j_1' });
  assert.throws(() => parseArgs(['--submit', '--id', 'r1', '--source', 's']), /--type, --id and --source are required/);
  assert.throws(() => parseArgs(['--submit', '--type', 'video', '--id', 'r1', '--source', 's']), /unknown --type 'video'/);
  assert.throws(() => parseArgs(['--submit', '--type', 'code', '--id', 'r1', '--source']), /--source needs a value/);
  assert.throws(() => parseArgs(['--status', 'j_1', '--type', 'code']), /is not valid with --status/);
  assert.throws(() => parseArgs(['--submit', '--repo', 'r1', '--type', 'code', '--id', 'r1', '--source', 's']), /unknown option '--repo'/);
  assert.throws(() => parseArgs(['stray']), /unexpected argument 'stray'/);
  assert.throws(() => parseArgs([]), /usage:/);
});

test('http: only code is accepted; other types are refused, unknown types are a bad request', async () => {
  const queue = new JobQueue(':memory:');
  const server = createIngestServer(config(), queue);
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', () => resolve()));
  const base = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
  const post = (body: unknown) => fetch(`${base}/jobs`, {
    method: 'POST', headers: { authorization: 'Bearer admin-secret', 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  try {
    const docs = await post({ type: 'docs', repoId: 'r1', source: 's' });
    assert.equal(docs.status, 422);
    assert.match((await docs.json() as { error: string }).error, /type 'docs' is not supported yet/);
    const bogus = await post({ type: 'video', repoId: 'r1', source: 's' });
    assert.equal(bogus.status, 400);
    const missing = await post({ repoId: 'r1', source: 's' });
    assert.equal(missing.status, 400);
    const unauth = await fetch(`${base}/jobs`, { method: 'POST', body: '{}' });
    assert.equal(unauth.status, 401);
  } finally {
    await new Promise(resolve => server.close(resolve));
    queue.close();
  }
});
