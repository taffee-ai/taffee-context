import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { configFromEnv } from './config.ts';
import { createIngestServer } from './http.ts';
import { JobQueue } from './queue.ts';
import { startWorkers } from './worker.ts';

const config = configFromEnv();
mkdirSync(dirname(config.queueFile), { recursive: true });
mkdirSync(config.workspace, { recursive: true });
const queue = new JobQueue(config.queueFile);
const log = (message: string) => console.log(`${new Date().toISOString()} ${message}`);

startWorkers({ queue, count: config.workers, workspace: config.workspace, leaseMs: config.leaseMs, log });
createIngestServer(config, queue).listen(config.port, '0.0.0.0', () => log(`ingestion service on :${config.port}, workers=${config.workers}`));
