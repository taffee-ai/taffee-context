import { pathToFileURL } from 'node:url';
import { SOURCE_TYPES, type SourceType } from './types.ts';

export type Command =
  | { kind: 'submit'; type: SourceType; id: string; source: string; ref?: string }
  | { kind: 'status'; jobId: string };

export const USAGE = `usage:
  taffee-ingest --submit --type <${SOURCE_TYPES.join('|')}> --id <name> --source <url-or-path> [--ref <ref>]
  taffee-ingest --status <job-id>

env: INGEST_URL (e.g. http://127.0.0.1:8790), INGEST_TOKEN`;

/** Parses the command line. Throws with a usage message on anything it does not understand. */
export function parseArgs(args: string[]): Command {
  let submit = false;
  const flags = new Map<string, string>();
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--submit') { submit = true; continue; }
    if (arg === '--status' || arg === '--type' || arg === '--id' || arg === '--source' || arg === '--ref') {
      const value = args[i + 1];
      if (value === undefined || value.startsWith('--')) throw new Error(`${arg} needs a value\n${USAGE}`);
      flags.set(arg, value);
      i++;
      continue;
    }
    if (arg.startsWith('--')) throw new Error(`unknown option '${arg}'\n${USAGE}`);
    throw new Error(`unexpected argument '${arg}'\n${USAGE}`);
  }
  if (submit && flags.has('--status')) throw new Error(`--status is not valid with --submit\n${USAGE}`);
  if (flags.has('--status')) {
    for (const key of flags.keys()) if (key !== '--status') throw new Error(`${key} is not valid with --status\n${USAGE}`);
    return { kind: 'status', jobId: flags.get('--status') as string };
  }
  if (!submit) throw new Error(USAGE);
  const type = flags.get('--type');
  const id = flags.get('--id');
  const source = flags.get('--source');
  if (!type || !id || !source) throw new Error(`--type, --id and --source are required\n${USAGE}`);
  if (!(SOURCE_TYPES as readonly string[]).includes(type)) throw new Error(`unknown --type '${type}'\n${USAGE}`);
  const ref = flags.get('--ref');
  return { kind: 'submit', type: type as SourceType, id, source, ...(ref ? { ref } : {}) };
}

async function call(method: 'GET' | 'POST', path: string, body?: unknown): Promise<unknown> {
  const base = process.env.INGEST_URL;
  const token = process.env.INGEST_TOKEN;
  if (!base || !token) throw new Error(`INGEST_URL and INGEST_TOKEN must be set\n${USAGE}`);
  const response = await fetch(new URL(path, base), {
    method,
    headers: { authorization: `Bearer ${token}`, ...(body ? { 'content-type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await response.json();
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${JSON.stringify(json)}`);
  return json;
}

export async function run(command: Command): Promise<unknown> {
  if (command.kind === 'status') return call('GET', `/jobs/${command.jobId}`);
  return call('POST', '/jobs', {
    type: command.type, repoId: command.id, source: command.source, ...(command.ref ? { ref: command.ref } : {}),
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    console.log(JSON.stringify(await run(parseArgs(process.argv.slice(2))), null, 2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(2);
  }
}
