import { randomUUID } from 'node:crypto';
import { runPipeline } from './pipeline.ts';
import type { JobQueue } from './queue.ts';

export interface WorkerOptions {
  queue: JobQueue;
  count: number;
  workspace: string;
  leaseMs: number;
  log: (message: string) => void;
}

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/** Starts `count` loops. Each claims a job, keeps its lease alive, runs the pipeline, and records the result. */
export function startWorkers(options: WorkerOptions): { stop: () => void } {
  let running = true;
  const loop = async (owner: string): Promise<void> => {
    while (running) {
      const job = options.queue.claim(owner, options.leaseMs);
      if (!job) { await sleep(1000); continue; }
      options.log(`job ${job.id} ${job.repoId}@${job.sha} started`);
      const heartbeat = setInterval(() => options.queue.heartbeat(job.id, owner, options.leaseMs), options.leaseMs / 3);
      try {
        await runPipeline(job, options.workspace, step => options.queue.setStep(job.id, step));
        options.queue.finish(job.id, 'ready', null);
        options.log(`job ${job.id} ready`);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        options.queue.finish(job.id, 'failed', message);
        options.log(`job ${job.id} failed: ${message}`);
      } finally {
        clearInterval(heartbeat);
      }
    }
  };
  for (let i = 0; i < options.count; i++) void loop(`worker-${randomUUID().slice(0, 8)}`);
  return { stop: () => { running = false; } };
}
