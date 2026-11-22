import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { extractRepository } from './ingestion/extract/code/graphify-extractor.ts';
import { loadSnapshot } from './ingestion/load/neo4j-loader.ts';
import { configFromEnv } from './ingestion/chunks/chunker.ts';
import { buildSemanticLayer } from './ingestion/load/neo4j-semantic-loader.ts';
import { graphHash, validateSnapshot } from './ingestion/load/validate-snapshot.ts';
import { verifyStoredSnapshot } from './ingestion/load/verify-stored.ts';
import { queryGraph, validateQuery } from './retrieval/query/neo4j-query.ts';
import { searchChunks, validateSearch } from './retrieval/query/neo4j-search.ts';
import { connectNeo4j } from './storage/neo4j/client.ts';
import { initializeSchema } from './storage/neo4j/schema.ts';
import { snapshotId, type RepositorySnapshot } from './types.ts';

async function withDatabase<T>(work: (connection: ReturnType<typeof connectNeo4j>) => Promise<T>): Promise<T> {
  const connection = connectNeo4j();
  try { return await work(connection); }
  finally { await connection.close(); }
}

export async function main(args = process.argv.slice(2)): Promise<void> {
  const [command, ...rest] = args;
  if (command === 'init-schema' && rest.length === 0) {
    await withDatabase(initializeSchema);
    process.stdout.write('Schema ready\n');
  } else if ((command === 'extract' || command === 'ingest') && rest.length === 4) {
    const [repoId, repositoryPath, commitSHA, output] = rest;
    const snapshot = await extractRepository({ repoId, repositoryPath, commitSHA });
    if (output !== '-') {
      try { await writeFile(output, JSON.stringify(snapshot, null, 2) + '\n', { flag: 'wx', mode: 0o600 }); }
      catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
        const saved = validateSnapshot(JSON.parse(await readFile(output, 'utf8')) as RepositorySnapshot);
        if (graphHash(saved) !== graphHash(snapshot)) throw new Error('Existing snapshot file has different content');
      }
    }
    if (command === 'ingest') {
      const result = await withDatabase(async connection => {
        await initializeSchema(connection);
        return loadSnapshot(connection, snapshot);
      });
      process.stdout.write(JSON.stringify({ ...result, graphHash: graphHash(snapshot),
        artifactHash: snapshot.artifactHash, nodes: snapshot.nodes.length, edges: snapshot.edges.length }) + '\n');
    } else if (output === '-') process.stdout.write(JSON.stringify(snapshot) + '\n');
    else process.stdout.write(JSON.stringify({ output, graphHash: graphHash(snapshot), artifactHash: snapshot.artifactHash }) + '\n');
  } else if (command === 'load' && rest.length === 1) {
    const snapshot = validateSnapshot(JSON.parse(await readFile(rest[0], 'utf8')) as RepositorySnapshot);
    const result = await withDatabase(async connection => {
      await initializeSchema(connection);
      return loadSnapshot(connection, snapshot);
    });
    process.stdout.write(JSON.stringify({ ...result, graphHash: graphHash(snapshot) }) + '\n');
  } else if (command === 'query' && rest.length >= 2 && rest.length <= 5) {
    const [repoId, operation, symbol, commitSHA, limit] = rest;
    const query = validateQuery({ repoId, operation, ...(symbol === '-' || symbol === undefined ? {} : { symbol }),
      ...(commitSHA === '-' || commitSHA === undefined ? {} : { commitSHA }),
      ...(limit === undefined ? {} : { limit: Number(limit) }) });
    const result = await withDatabase(connection => queryGraph(connection, query));
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  } else if (command === 'verify' && rest.length === 3) {
    const [repoId, commitSHA, file] = rest;
    const snapshot = validateSnapshot(JSON.parse(await readFile(file, 'utf8')) as RepositorySnapshot);
    if (snapshot.repoId !== repoId || snapshot.commitSHA !== commitSHA) throw new Error('Snapshot identity mismatch');
    const result = await withDatabase(connection => verifyStoredSnapshot(connection, snapshot));
    process.stdout.write(JSON.stringify(result) + '\n');
  } else if (command === 'chunk-embed' && rest.length === 3) {
    const [repoId, repositoryPath, commitSHA] = rest;
    const result = await withDatabase(async connection => {
      await initializeSchema(connection);
      return buildSemanticLayer(connection, { repoId, repositoryPath, commitSHA }, { config: configFromEnv() });
    });
    process.stdout.write(JSON.stringify(result) + '\n');
  } else if (command === 'search' && rest.length >= 2 && rest.length <= 4) {
    const [repoId, query, commitSHA, topK] = rest;
    const search = validateSearch({ repoId, query, ...(commitSHA === undefined || commitSHA === '-' ? {} : { commitSHA }),
      ...(topK === undefined ? {} : { topK: Number(topK) }) });
    const result = await withDatabase(connection => searchChunks(connection, search));
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  } else {
    throw new Error('Usage: init-schema | extract <repoId> <repoPath> <sha> <snapshot.json|-> | ingest <repoId> <repoPath> <sha> <snapshot.json|-> | load <snapshot.json> | query <repoId> <operation> [symbol|-] [sha|-] [limit] | verify <repoId> <sha> <snapshot.json> | chunk-embed <repoId> <repoPath> <sha> | search <repoId> <query> [sha|-] [topK]');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`); process.exitCode = 1; });
}
