# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately, through GitHub: on this repository's **Security** tab, choose **Report a vulnerability**. Do not open a public issue, pull request or discussion for a vulnerability.

A useful report says:

- which commit you tested;
- the component (see the scope below) and the request, tool call, repository or snapshot involved;
- the steps to reproduce, and what happened compared with what you expected;
- what an attacker gains: for example a tool call answered without a valid token, a file read from outside the indexed repository, a repository ingested from a source the operator did not allow, or a secret returned in a reply.

We will confirm that we received the report, keep you informed while we work on it, and agree with you when the details are published. We will credit you in the advisory unless you ask us not to.

## Supported versions

There is no tagged release yet.

| Version | Supported |
|---|---|
| `main` | Yes |
| Earlier commits | No |

## Scope

In scope: everything in this repository, in particular

- **The ingestion service** (`context/service/`): an API call other than `/healthz` accepted without the admin token, a Git URL cloned although it matches no entry in `INGEST_SOURCE_ALLOWLIST`, a local path accepted outside `INGEST_LOCAL_ROOT` (including through a symbolic link), or a snapshot published (`ready`) before its verification passed.
- **Ingestion** (`context/ingestion/`): source read from anything other than the exact commit (untracked files, symbolic links or submodules), a bound that can be exceeded (50,000 nodes, 200,000 edges, 32 MiB of Graphify output, 5,000 files, 1 MiB per file, 20,000 chunks), or input from a repository that reaches a shell or command line as anything other than a plain argument.
- **The MCP server** (`context/serving/mcp/server.py`): a tool call answered without a valid bearer token, a way around the per-caller rate limit or the query time limit, `read_code` returning anything other than an indexed file at the snapshot's commit, a staged (unpublished) snapshot visible to a caller, a write to Neo4j through any tool, or an internal error, credential or token included in a reply.
- **The context pack** (`context/serving/mcp/turbo_*.py`): `GitBlobReader` reading outside the repository or at a commit other than the one requested, or the pack returning data from a snapshot other than the requested one.
- **The read path** (`python/taffee_context/storage/read_view.py`, `python/taffee_context/storage/neo4j_store.py`): a write that succeeds through the read-only view or a read transaction.
- **The graph query tool** (`context/retrieval/query/graph-query-tool.ts`): a repository outside `TAFFEE_CONTEXT_REPOS` queried, or caller-supplied Cypher executed.
- **The evaluation harness** (`eval/harness/run.py`): a file tool given to a model that reads outside the checkout it was given.

## Behaviour that is intentional

These are documented properties of the current deployment, not vulnerabilities. Reports that show they are worse than documented are welcome.

- **One token, every repository.** Each MCP caller has its own token, and every token can read every ready repository on that server. There are no per-repository or per-user permissions. Tokens are stored in clear text in the tokens file; a token is revoked by deleting its line and restarting the server.
- **The MCP server holds the Neo4j admin password.** Neo4j Community has no read-only users. Read-only access is enforced by the code (the server holds only `ReadOnlyView`) and by Neo4j (every read runs in a read-only transaction). Keep Neo4j's own ports off the network. See decision D-005-7 in [docs/design/005_storage_interface/DECISIONS.md](docs/design/005_storage_interface/DECISIONS.md).
- **Self-signed certificate.** `gen_cert.sh` creates a self-signed certificate for the MCP server, and clients are told to trust it (`MCP_INSECURE=1`). Deployments that need a managed certificate terminate TLS in front of the server.
- **The ingestion service speaks plain HTTP.** It listens on all interfaces without TLS and requires the admin token on every call except `/healthz`. Deployments keep its port on a private network or put TLS in front of it.
- **Source allowlist entries are string prefixes.** A source is allowed when it starts with an entry, so `https://github.com/org` also matches `https://github.com/org-other/…`. End each entry with `/`.
- **The operator CLI has no authentication.** `npm run context -- …` runs with whatever database access the host gives it; access is controlled by who can use the host and the database.
- **Health endpoints are open.** `/healthz` on both services answers without a token and returns only a liveness flag.
- **Snapshot files contain source metadata.** Files written by `extract` and `ingest` include file paths and symbol names from the ingested repository; handle them as you would the repository.

See the [README](README.md), the [operator guide](docs/guides/operator-guide.md) and the [MCP server README](context/serving/mcp/README.md) for details.
