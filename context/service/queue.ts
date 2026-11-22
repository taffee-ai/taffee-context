import { randomUUID } from 'node:crypto';
import Database from 'better-sqlite3';

export type JobStatus = 'queued' | 'running' | 'ready' | 'failed';
export type SourceKind = 'url' | 'path';

export interface Job {
  id: string;
  repoId: string;
  source: string;
  sourceKind: SourceKind;
  sha: string;
  status: JobStatus;
  step: string | null;
  error: string | null;
  attempts: number;
  createdAt: number;
  updatedAt: number;
  leaseOwner: string | null;
  leaseExpires: number | null;
}

interface Row {
  id: string; repo_id: string; source: string; source_kind: SourceKind; sha: string; status: JobStatus;
  step: string | null; error: string | null; attempts: number; created_at: number; updated_at: number;
  lease_owner: string | null; lease_expires: number | null;
}

const toJob = (r: Row): Job => ({
  id: r.id, repoId: r.repo_id, source: r.source, sourceKind: r.source_kind, sha: r.sha, status: r.status,
  step: r.step, error: r.error, attempts: r.attempts, createdAt: r.created_at, updatedAt: r.updated_at,
  leaseOwner: r.lease_owner, leaseExpires: r.lease_expires,
});

export class JobQueue {
  private readonly db: Database.Database;

  constructor(file: string) {
    this.db = new Database(file);
    this.db.pragma('journal_mode = WAL');
    this.db.exec(`CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, repo_id TEXT NOT NULL, source TEXT NOT NULL, source_kind TEXT NOT NULL,
      sha TEXT NOT NULL, status TEXT NOT NULL, step TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, lease_owner TEXT, lease_expires INTEGER,
      UNIQUE (repo_id, sha))`);
  }

  close(): void { this.db.close(); }

  get(id: string): Job | null {
    const row = this.db.prepare('SELECT * FROM jobs WHERE id = ?').get(id) as Row | undefined;
    return row ? toJob(row) : null;
  }

  /** One job per (repo, commit). A repeat request returns the existing job; a failed one is queued again. */
  enqueue(input: { repoId: string; source: string; sourceKind: SourceKind; sha: string }): { job: Job; created: boolean } {
    return this.db.transaction((): { job: Job; created: boolean } => {
      const now = Date.now();
      const existing = this.db.prepare('SELECT * FROM jobs WHERE repo_id = ? AND sha = ?').get(input.repoId, input.sha) as Row | undefined;
      if (existing) {
        if (existing.status === 'failed') {
          this.db.prepare("UPDATE jobs SET status = 'queued', step = NULL, error = NULL, updated_at = ? WHERE id = ?").run(now, existing.id);
        }
        return { job: this.get(existing.id) as Job, created: false };
      }
      const id = randomUUID();
      this.db.prepare(`INSERT INTO jobs (id, repo_id, source, source_kind, sha, status, attempts, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?)`).run(id, input.repoId, input.source, input.sourceKind, input.sha, now, now);
      return { job: this.get(id) as Job, created: true };
    }).immediate();
  }

  /** Takes the oldest queued job whose repo has no running job. Expired leases go back to the queue first. */
  claim(owner: string, leaseMs: number): Job | null {
    return this.db.transaction((): Job | null => {
      const now = Date.now();
      this.db.prepare(`UPDATE jobs SET status = 'queued', lease_owner = NULL, lease_expires = NULL, updated_at = ?
        WHERE status = 'running' AND lease_expires < ?`).run(now, now);
      const next = this.db.prepare(`SELECT * FROM jobs j WHERE j.status = 'queued'
        AND NOT EXISTS (SELECT 1 FROM jobs r WHERE r.repo_id = j.repo_id AND r.status = 'running')
        ORDER BY j.created_at, j.rowid LIMIT 1`).get() as Row | undefined;
      if (!next) return null;
      this.db.prepare(`UPDATE jobs SET status = 'running', attempts = attempts + 1, lease_owner = ?, lease_expires = ?, updated_at = ?
        WHERE id = ?`).run(owner, now + leaseMs, now, next.id);
      return this.get(next.id);
    }).immediate();
  }

  heartbeat(id: string, owner: string, leaseMs: number): boolean {
    const result = this.db.prepare('UPDATE jobs SET lease_expires = ?, updated_at = ? WHERE id = ? AND lease_owner = ?')
      .run(Date.now() + leaseMs, Date.now(), id, owner);
    return result.changes === 1;
  }

  setStep(id: string, step: string): void {
    this.db.prepare('UPDATE jobs SET step = ?, updated_at = ? WHERE id = ?').run(step, Date.now(), id);
  }

  finish(id: string, status: 'ready' | 'failed', error: string | null): void {
    this.db.prepare(`UPDATE jobs SET status = ?, error = ?, lease_owner = NULL, lease_expires = NULL, updated_at = ?
      WHERE id = ?`).run(status, error, Date.now(), id);
  }
}
