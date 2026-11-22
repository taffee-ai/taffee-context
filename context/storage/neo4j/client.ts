import neo4j, { type Driver } from 'neo4j-driver';

export interface Neo4jConnection {
  driver: Driver;
  database: string;
  close(): Promise<void>;
}
export function connectNeo4j(env: NodeJS.ProcessEnv = process.env): Neo4jConnection {
  const uri = env.NEO4J_URI;
  const password = env.NEO4J_PASSWORD;
  if (!uri || !password) throw new Error('Set NEO4J_URI and NEO4J_PASSWORD');
  const parsed = new URL(uri);
  if (!['bolt:', 'bolt+s:', 'bolt+ssc:', 'neo4j:', 'neo4j+s:', 'neo4j+ssc:'].includes(parsed.protocol)
      || parsed.username || parsed.password) throw new Error('Invalid NEO4J_URI');
  const driver = neo4j.driver(uri, neo4j.auth.basic(env.NEO4J_USER ?? 'neo4j', password), {
    connectionTimeout: 3000, connectionAcquisitionTimeout: 3000,
    maxTransactionRetryTime: 5000, maxConnectionPoolSize: 4,
  });
  return { driver, database: env.NEO4J_DATABASE ?? 'neo4j', close: () => driver.close() };
}
