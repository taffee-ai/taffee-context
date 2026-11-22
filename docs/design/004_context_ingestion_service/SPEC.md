# Context ingestion service (draft)

**Status:** implemented in `taffee-context/context/service/` and tested on the execution host (unit and database tests; two end-to-end ingests through the HTTP API). Still open: the stack in `taffee-core/infra/`, the service image, and the `taffee-ingest` command run end to end.

## Purpose

A containerised HTTP service that turns one repository at one commit into a searchable Context snapshot. It runs the same steps as today's manual commands: `ingest` (Graphify extraction and load into Neo4j), then `chunk-embed` (chunks and vectors), then `verify`.

It is a **write** service. It is separate from the MCP server, which stays read-only.

## Non-goals

- Serving queries. That stays in the MCP server.
- Replacing the CLI. The CLI remains the operator tool; the service calls the same code.

## Deployment

The stack is defined once, in `taffee-core/infra/`, as one compose file that starts three core services:

| Service | Image source | Role | Neo4j access |
|---|---|---|---|
| Neo4j | `neo4j:5.26.0-community` | Database | n/a |
| Ingestion service | Built from `taffee-context` | Writes: Graphify, chunk-embed, job queue | Read and write, on its own network |
| MCP server | Built from `taffee-context` | Reads: serves agents | Read-only user, on a separate network |

- The code and Dockerfiles stay in `taffee-context`. `infra/` only wires the services together, pins their versions, and holds the stack's secrets and volumes.
- The ingestion service has its own volume for clones and the SQLite job file. It has no access to the MCP server's files.
- The MCP server connects with a database user that can only read, so the read-only rule is enforced by the database, not only by the code.
- Qwen is an optional profile, off unless enabled.
- Memory and CPU limits are set in the stack file. The embedding model needs about 1 GB.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST /jobs` | body: `repoId`, `source` (Git URL from the allowlist), `ref` (branch or tag) | Resolve `ref` to a full SHA, start a job, return the job ID |
| `GET /jobs/{id}` | | Status: `queued`, `running`, `ready`, `failed`, with step and error |
| `GET /repos` | | Repos and their ready commits, for operators |
| `GET /healthz` | | Liveness; also checks Neo4j reachability |

Local filesystem paths are not accepted by default (see **OPEN** below).

## Command-line usage

`taffee-ingest` is a client of this service. It submits jobs and reports their status. It doesn't run ingestion itself.

```
taffee-ingest --submit --type <type> --id <name> --source <url-or-path> [--ref <ref>]
taffee-ingest --status <job-id>
```

- `--type` selects the pipeline: `code`, `docs`, `tables`, `logs`, `pdf` or `unknown`. Only `code` is implemented. The others are rejected with "not supported yet" until built.
- `unknown` is stored as a blob: raw bytes, not parsed, not searchable by content.
- `--id` names the source in the database. (Assumption: this replaces the old `--repo`. Confirm.)
- `--source` is a Git URL or a local path, for code or any other file type. A local path must be under the service's configured root and on the same machine.
- `--ref` applies to Git URLs only. Without it, the newest release tag is used.
- `--submit` prints the job ID and the resolved commit. `--status` prints the job's current step.

## Pipeline for one job

1. Resolve `ref` to a full commit SHA. Record it.
2. Fetch that commit into the workspace (`git fetch --depth 1`, as DEF-041 established).
3. `ingest`: extract with Graphify, save the snapshot, load into Neo4j.
4. `chunk-embed` for the same SHA.
5. `verify` the snapshot and its semantic layer.
6. Mark the commit `ready`. Only a verified commit is ever visible to the MCP server.

A failed step leaves the commit not ready, so agents never see a partial snapshot.

## Idempotency, queueing and concurrency

Many callers can post jobs at once, and a job is several steps that are not atomic together. The rules:

- **Key:** a job is identified by `(repoId, sha)`. A second `POST` for the same key returns the existing job, with no new work. Repeating a finished job returns `unchanged`.
- **Queue is durable.** Jobs are stored where a restart can't lose them (see **OPEN** 2). An in-memory queue is not acceptable with more than one caller.
- **Worker count is configurable** (`INGEST_WORKERS`, default 1). Jobs are taken in arrival order, subject to the per-repo rule below. The default of 1 means one repo is ingested at a time across the whole service, which keeps runs easy to debug and validate. Raise it only when debugging is no longer the bottleneck.
- **Hard rule: only one worker may be graphifying or chunking a given repo at a time.** A per-repo lock enforces it. Jobs for different repos can run in parallel, up to the worker count.
- **Bounded intake:** when the queue is full, `POST /jobs` returns `429`. Each caller also has a rate limit, so one caller can't fill the queue.
- **Leases are persisted** with an owner and an expiry, renewed while a job runs. If the worker dies, the lease expires and the job is retried from its last completed step.
- **Retries** use backoff and a fixed maximum. After the maximum, the job is `failed` and stays failed until a new request arrives.
- **Only the final step publishes.** Ingest loads the structure in one transaction, and chunk-embed is resumable. The `ready` flag is written last, in a single write. Until then, the MCP server doesn't list the commit, so partial state is never visible.
- **A newer job never cancels a running one** for the same repo. It waits in the queue.

## Auth

- **Callers:** an admin token, separate from the per-agent MCP tokens. Only CI and operators hold it. Stored hashed on the service side.
- **Git access:** a read-only credential (deploy key or GitHub App token) held by the service as a secret, with a fixed list of repos it may clone.
- **Neo4j:** credentials as a secret, never in the image or in a request.

## Configuration (environment)

- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- `INGEST_ADMIN_TOKEN_HASH`
- `INGEST_SOURCE_ALLOWLIST` (repo URLs the service may clone)
- `INGEST_WORKERS` (default 1; the number of jobs that may run at once across different repos)
- `INGEST_LOCAL_ROOT` (the only folder local-path sources may be read from)
- Pinned Graphify version and embedding model revision (must match the MCP image; see the version list in the deployment notes)

## Triggers

- **OPEN:** CI on release tags only (for example `v*`), not on every commit. This matches "at least for major releases".

## Open decisions

1. **Runtime:** wrap the existing Node CLI functions in an HTTP layer (recommended, no logic rewrite), or write a new service.
2. **Job state and queue: decided.** SQLite, as a single file on the service's own volume, in WAL mode. It is durable, needs no extra container, and fits the single-worker design. The limit is one service container with one writer. If the service ever runs as several containers, move the same tables to PostgreSQL.
3. **Default commit: decided.** When an agent names no commit, it gets the latest release tag that has a `ready` snapshot.
4. **Local paths: decided.** Both Git URLs and local paths are allowed. A local path must be under `INGEST_LOCAL_ROOT` on the service's machine. Folder upload from a laptop to a remote service is not planned yet.
5. **Network:** how CI and the service reach Neo4j, given it listens on loopback only today.

## Acceptance checks

- Ingest a public repository at a tag; the job reaches `ready`.
- Repeat the same request: `unchanged`, no Graphify run.
- Request a commit not on the allowlist: refused.
- Kill the service mid-job: the commit is not `ready`; a re-run completes it.
- The MCP server lists the repo and answers a query, with no restart.
