import { createHash } from 'node:crypto';

export interface ServiceConfig {
  port: number;
  /** SHA-256 hex of the admin token. The token itself is never stored in the service. */
  adminTokenHash: string;
  sourceAllowlist: string[];
  localRoot: string | null;
  workers: number;
  queueFile: string;
  workspace: string;
  leaseMs: number;
}

export function hashToken(token: string): string {
  return createHash('sha256').update(token).digest('hex');
}

function required(env: NodeJS.ProcessEnv, name: string): string {
  const value = env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

export function configFromEnv(env: NodeJS.ProcessEnv = process.env): ServiceConfig {
  const workers = Number(env.INGEST_WORKERS ?? '1');
  if (!Number.isInteger(workers) || workers < 1) throw new Error('INGEST_WORKERS must be a positive integer');
  return {
    port: Number(env.INGEST_PORT ?? '8790'),
    adminTokenHash: required(env, 'INGEST_ADMIN_TOKEN_HASH'),
    sourceAllowlist: (env.INGEST_SOURCE_ALLOWLIST ?? '').split(',').map(s => s.trim()).filter(Boolean),
    localRoot: env.INGEST_LOCAL_ROOT ? env.INGEST_LOCAL_ROOT : null,
    workers,
    queueFile: env.INGEST_QUEUE_FILE ?? '/var/lib/taffee-ingest/jobs.sqlite',
    workspace: env.INGEST_WORKSPACE ?? '/var/lib/taffee-ingest/work',
    leaseMs: Number(env.INGEST_LEASE_MS ?? '120000'),
  };
}
