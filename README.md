# taffee-context

The Context pillar of TAFFEE. It turns a Git repository at one exact commit into a graph of its code in Neo4j, adds semantic chunks and vectors for search, and serves that graph to AI agents through a read-only MCP server.

**Status: experimental.** Tested on the execution host. The ingestion service and `taffee-ingest` were run end to end on 2026-11-22, with a Git URL source and a local-path source.

## Design goals

taffee-context is a system-design exercise. It is not a performance claim. It is built for the case where many agents and developers work across many repositories, up to thousands of repositories and hundreds of developers, and is meant to be useful as well to one person with many projects on one machine. We built it to have:

1. **One context store, built once and shared.** Each repository is ingested once per commit and published as a read-only snapshot. Any number of agents and sessions read the same snapshot through the MCP server, each with its own token and rate limit.
2. **Structure for questions grep can't answer directly.** The graph serves callers, impact ("what does changing this affect") and module structure (communities, central nodes). *Known gap:* calls made from inside nested functions are not yet recorded as edges.
3. **Self-hosted, with local embeddings.** Neo4j runs on your machine and the embedding model runs locally, so indexing sends no code to an outside service. *Scope:* this covers indexing and storage. If your agent uses a hosted model, the code it retrieves is still sent to that model.

Not yet built or measured: questions that span several repositories, and anything at large scale. Both are on the roadmap.

### What we measured

In our [first public evaluation](eval/results/2026-11-14-fastapi/REPORT.md) on FastAPI (3 models, 30 questions, 1,080 runs), grep alone was as accurate as grep plus the graph, at lower token cost. On a small, well-known repository the graph did not make agents better. The method, raw runs and negative results are published so anyone can check them. The next evaluation targets many repositories and code the models have not memorised.

### Built on Graphify

taffee-context uses [Graphify](https://github.com/Graphify-Labs/graphify) in code-only mode (tree-sitter, no LLM) to build each repository's code graph, and runs Graphify's own graph queries in the MCP server. It adds shared, persistent storage for many repositories and commits in Neo4j, verified snapshots, local semantic search, a secured read-only MCP server and an ingestion service. Why code-only: [decision 006](docs/design/001_context_code_graph/DECISIONS.md). Third-party licenses: [NOTICE](NOTICE).

## Parts

| Part | Where | Does |
|---|---|---|
| Ingestion service | `context/service/` | HTTP API and job queue. Ingests and embeds one repo at one commit, then publishes it. Writes to Neo4j. |
| `taffee-ingest` | `context/service/taffee-ingest` | Command-line client for the ingestion service. |
| Ingestion code | `context/ingestion/` | Graphify extraction, the structural loader, chunking and embeddings. The service and the CLI both call it. |
| CLI | `context/cli.ts`, run as `npm run context -- ...` | Operator commands: `ingest`, `chunk-embed`, `verify`, `query`, `search`. Runs one command and exits. |
| MCP server | `context/serving/mcp/` | Read-only server over the graph and chunks. 12 tools, token authentication and rate limits. See its [README](context/serving/mcp/README.md). |
| Storage | `context/storage/`, `context/retrieval/` | Neo4j client, schema and queries. |

Neo4j itself is not in this repository. It is started from `taffee-core/infra/`, the umbrella repository, because every pillar shares it.

## Ingestion service

A repo is ingested in these steps, in order. A commit only becomes visible to readers at the last step.

1. `fetch`: clone exactly one commit (Git URL sources only).
2. `extract`: Graphify builds the code graph.
3. `load`: the graph is written to Neo4j as **staged** (hidden from readers).
4. `chunk-embed`: the code is split and embedded, using the local model.
5. `verify`: the stored graph is compared with the extracted one.
6. `publish`: the snapshot is marked **ready**.

Job states are `queued`, `running`, `ready` and `failed`.

### Rules

- **One job per repo and commit.** A repeat request returns the existing job. A failed job is queued again when it is requested again.
- **One worker per repo.** A second commit of the same repo waits until the first finishes.
- **Concurrency** across repos is set by `INGEST_WORKERS` (default 1, so one repo at a time).
- **Sources:**
  - *Git URL*: must match a prefix in `INGEST_SOURCE_ALLOWLIST`. Without `--ref`, the newest `vMAJOR.MINOR.PATCH` tag is used.
  - *Local path*: must be inside `INGEST_LOCAL_ROOT`, on the same machine as the service, with no uncommitted changes. HEAD is used, and `--ref` is refused.
- **Admin token:** every API call except health needs `Authorization: Bearer <token>`. The service stores only the SHA-256 hash of the token.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `INGEST_ADMIN_TOKEN_HASH` | required | SHA-256 hex of the admin token |
| `INGEST_PORT` | `8790` | HTTP port |
| `INGEST_SOURCE_ALLOWLIST` | empty | Comma-separated Git URL prefixes that may be cloned |
| `INGEST_LOCAL_ROOT` | unset | Folder that local-path sources must be inside; unset disables local paths |
| `INGEST_WORKERS` | `1` | Jobs that may run at once, across different repos |
| `INGEST_QUEUE_FILE` | `/var/lib/taffee-ingest/jobs.sqlite` | SQLite job queue; keep it on a persistent volume |
| `INGEST_WORKSPACE` | `/var/lib/taffee-ingest/work` | Where Git sources are cloned |
| `INGEST_LEASE_MS` | `120000` | How long a worker holds a job without a heartbeat before it is retried |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | required | Database connection |

The Graphify and embedding settings are the same as for the CLI. See the [operator guide](docs/guides/operator-guide.md).

### Running it

```sh
npm install
export INGEST_ADMIN_TOKEN_HASH="$(printf %s "$TOKEN" | sha256sum | cut -d' ' -f1)"
export INGEST_SOURCE_ALLOWLIST="git@github.com:your-org/"
export INGEST_LOCAL_ROOT="/srv/repos"
export NEO4J_URI=bolt://127.0.0.1:17687 NEO4J_USER=neo4j NEO4J_PASSWORD=...
npm run service
```

Give it about 2.5 GB of memory: the embedding model uses about 1 GB and runs next to the service.

### Using it

```sh
export INGEST_URL=http://127.0.0.1:8790
export INGEST_TOKEN=...   # the token whose hash is in INGEST_ADMIN_TOKEN_HASH

# Git URL, latest release tag
context/service/taffee-ingest --submit --type code --id demo-shop --source git@github.com:your-org/demo-shop.git

# Git URL, a specific tag
context/service/taffee-ingest --submit --type code --id demo-shop --source git@github.com:your-org/demo-shop.git --ref v1.2.0

# Local folder on the service's machine
context/service/taffee-ingest --submit --type code --id demo-shop --source /srv/repos/demo-shop

# Progress
context/service/taffee-ingest --status <job-id>
```

`--submit` prints the job ID and the commit SHA. Re-running the same request does no new work.

### Testing

```sh
npm run typecheck
npm test                                  # unit tests; database tests are skipped
TAFFEE_NEO4J_TEST=1 npm test              # also runs the database tests (needs NEO4J_*)
```

The tests and the service are run on the execution host, in the container described in the operator guide.

## Documentation

- [Operator guide](docs/guides/operator-guide.md): installation and CLI commands.
- [Data model](docs/guides/data-model.md): graph semantics.
- [Verification](docs/design/verification.md): evidence from remote runs.
- [Ingestion code notes](context/README.md).

To report a vulnerability, see [SECURITY.md](SECURITY.md).

**How Taffee is built.** Taffee began in August 2026 and has grown steadily since. Its authors have spent that time building the harness, testing ideas against real use and taking feedback from people in the industry. We write the code with AI coding tools (Claude, Codex and Antigravity) across every repository in [taffee-ai](https://github.com/taffee-ai). The architecture is worked out by people, together with those tools.

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
