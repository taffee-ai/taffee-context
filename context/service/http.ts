import { timingSafeEqual } from 'node:crypto';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { hashToken, type ServiceConfig } from './config.ts';
import type { JobQueue, SourceKind } from './queue.ts';
import { SOURCE_TYPES } from './types.ts';
import { isAllowedUrl, isUrlSource, resolveLocal, resolveUrl } from './sources.ts';

const REPO_ID = /^[a-z0-9][a-z0-9._-]{0,99}$/;
const MAX_BODY = 16 * 1024;

function send(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body) + '\n');
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > MAX_BODY) throw new HttpError(413, 'request body too large');
    chunks.push(chunk as Buffer);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new HttpError(400, 'body must be JSON'); }
}

class HttpError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

function authorized(req: IncomingMessage, expectedHash: string): boolean {
  const header = req.headers.authorization ?? '';
  const presented = Buffer.from(hashToken(header.replace(/^Bearer /, '')), 'utf8');
  const expected = Buffer.from(expectedHash, 'utf8');
  return presented.length === expected.length && timingSafeEqual(presented, expected);
}

export function createIngestServer(config: ServiceConfig, queue: JobQueue): Server {
  return createServer(async (req, res) => {
    try {
      if (req.method === 'GET' && req.url === '/healthz') return send(res, 200, { ok: true });
      if (!authorized(req, config.adminTokenHash)) return send(res, 401, { error: 'unauthorized' });

      if (req.method === 'POST' && req.url === '/jobs') {
        const body = (await readJson(req)) as { type?: unknown; repoId?: unknown; source?: unknown; ref?: unknown };
        if (typeof body.type !== 'string' || !(SOURCE_TYPES as readonly string[]).includes(body.type)) {
          throw new HttpError(400, `type must be one of ${SOURCE_TYPES.join(', ')}`);
        }
        if (body.type !== 'code') throw new HttpError(422, `type '${body.type}' is not supported yet`);
        if (typeof body.repoId !== 'string' || !REPO_ID.test(body.repoId)) throw new HttpError(400, 'repoId is invalid');
        if (typeof body.source !== 'string' || !body.source) throw new HttpError(400, 'source is required');
        const ref = typeof body.ref === 'string' ? body.ref : undefined;

        let sourceKind: SourceKind;
        let source: string;
        let sha: string;
        if (isUrlSource(body.source)) {
          if (!isAllowedUrl(body.source, config.sourceAllowlist)) throw new HttpError(403, 'source is not on the allowlist');
          sourceKind = 'url';
          source = body.source;
          sha = await resolveUrl(body.source, ref);
        } else {
          if (!config.localRoot) throw new HttpError(403, 'local paths are disabled (INGEST_LOCAL_ROOT is not set)');
          if (ref) throw new HttpError(400, 'ref is not supported for local paths; the checked-out HEAD is used');
          sourceKind = 'path';
          const local = await resolveLocal(body.source, config.localRoot);
          source = local.repositoryPath;
          sha = local.sha;
        }
        const { job, created } = queue.enqueue({ repoId: body.repoId, source, sourceKind, sha });
        return send(res, created ? 202 : 200, { jobId: job.id, status: job.status, repoId: job.repoId, sha: job.sha, created });
      }

      const match = /^\/jobs\/([0-9a-f-]{36})$/.exec(req.url ?? '');
      if (req.method === 'GET' && match) {
        const job = queue.get(match[1]);
        if (!job) return send(res, 404, { error: 'job not found' });
        const { leaseOwner: _owner, leaseExpires: _expires, ...publicJob } = job;
        return send(res, 200, publicJob);
      }
      return send(res, 404, { error: 'not found' });
    } catch (error) {
      if (error instanceof HttpError) return send(res, error.status, { error: error.message });
      const message = error instanceof Error ? error.message : 'internal error';
      return send(res, 422, { error: message });
    }
  });
}
