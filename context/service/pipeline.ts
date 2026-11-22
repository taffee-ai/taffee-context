import { join } from 'node:path';
import { configFromEnv as chunkConfigFromEnv } from '../ingestion/chunks/chunker.ts';
import { extractRepository } from '../ingestion/extract/code/graphify-extractor.ts';
import { loadSnapshot, publishSnapshot } from '../ingestion/load/neo4j-loader.ts';
import { buildSemanticLayer } from '../ingestion/load/neo4j-semantic-loader.ts';
import { verifyStoredSnapshot } from '../ingestion/load/verify-stored.ts';
import { connectNeo4j } from '../storage/neo4j/client.ts';
import { initializeSchema } from '../storage/neo4j/schema.ts';
import type { Job } from './queue.ts';
import { fetchUrl } from './sources.ts';

/** The same steps as the CLI, in order. Only the final publish makes the commit visible to readers. */
export async function runPipeline(job: Job, workspace: string, setStep: (step: string) => void): Promise<void> {
  const repositoryPath = job.sourceKind === 'url' ? join(workspace, job.repoId, job.sha) : job.source;
  if (job.sourceKind === 'url') {
    setStep('fetch');
    await fetchUrl(job.source, job.sha, repositoryPath);
  }
  setStep('extract');
  const snapshot = await extractRepository({ repoId: job.repoId, repositoryPath, commitSHA: job.sha });
  const connection = connectNeo4j();
  try {
    setStep('load');
    await initializeSchema(connection);
    await loadSnapshot(connection, snapshot, { publish: false });
    setStep('chunk-embed');
    await buildSemanticLayer(connection, { repoId: job.repoId, repositoryPath, commitSHA: job.sha }, { config: chunkConfigFromEnv() });
    setStep('verify');
    await verifyStoredSnapshot(connection, snapshot, { requireReady: false });
    setStep('publish');
    await publishSnapshot(connection, job.repoId, job.sha);
  } finally {
    await connection.close();
  }
}
