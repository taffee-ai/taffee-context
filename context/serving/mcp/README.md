# Code-graph MCP server

> `assemble_context_pack` is **experimental**, and its optional Laya and Qwen layers are off by default. It did not beat plain search in testing: see [003's status page](../../../docs/design/003_context_mcp_turbo/README.md).

Provides authenticated access, rate limiting, error sanitizing, and tool dispatching
adapted for TAFFEE's Neo4j schema. Implemented and run on the test host; see
`docs/design/verification.md` for results.

## Tools (12)

| Tool | What it does |
|---|---|
| `list_repos` | Repos that are ready (with semantic-layer state). Search by name, page through results, optionally list every commit |
| `graph_stats` | Node, edge, community and chunk counts |
| `get_node` | Where a symbol is, its type, community and number of connections (graphify's own code) |
| `explain` | One symbol with all its connections (direction, relation, confidence) |
| `get_neighbors` | Direct connections, optionally one relation type |
| `god_nodes` | Most-connected real entities (graphify's own function) |
| `get_community` | Everything in one community |
| `shortest_path` | Chain of relationships between two symbols |
| `query_graph` | Keyword search then a walk outward (graphify's own code), with an optional `context_filter` |
| `affected` | Impact analysis: what depends on a symbol (graphify's own code) |
| `semantic_search` | Find code by meaning, scoped to one snapshot (exact-scan fallback when the shared index is crowded). Flags chunks cut by characters or tokens |
| `read_code` | Committed source lines of an indexed file, at the snapshot's commit |

Every tool needs a `repo` (except `list_repos` and an empty-repo `semantic_search`). Results never mix repos.

## Run and test

Build the base image once (repo root): `docker build -f Dockerfile.base -t taffee-base:dev .`, then build `taffee-mcp:dev`
from `context/serving/mcp/Dockerfile` and run the unit tests inside it: `python -m pytest tests/`.

`NEO4J_URI=bolt://127.0.0.1:<port> NEO4J_PASSWORD=<password> bash context/serving/mcp/tests/run_tests.sh` starts a
low-limit server and runs the rate-limit check. A live test of every tool against a public fixture repository is not yet
included.

`run_tests.sh` generates a certificate and tokens if missing (in `TAFFEE_MCP_STATE`, default `~/.taffee-mcp`). The server needs `NEO4J_URI/USER/PASSWORD`, `TOKENS_FILE`
(lines of `name token`; it refuses to start with none), optional `SSL_CERTFILE`/`SSL_KEYFILE`, and `/repos` (Git clones,
read-only) for `read_code`. Optional: `QUERY_TIMEOUT_SECONDS` (15), `RATE_LIMIT_PER_MINUTE` (60 per caller),
`EMBED_MAX_TOKENS` (8192, must match ingestion), `MCP_PORT`.

The model loads on the first `semantic_search` (about 1.3 GB) and stays loaded, so run the container with a memory limit
and swap off (`--memory 2g --memory-swap 2g`).

## Command-line clients

`taffee-mcp` and `taffee-mcp-interactive` are wrappers around `client.py`, a command-line client supporting one-shot and interactive queries. They need the `mcp` and `httpx` packages; the wrappers use the repository's `.venv` if there is one
(`python3 -m venv .venv && .venv/bin/pip install "mcp==1.30.0" httpx`).

**One-shot commands** with `taffee-mcp`:
```
export MCP_URL=https://<host>:<port>/mcp MCP_TOKEN=<token> MCP_INSECURE=1     # MCP_INSECURE only for the self-signed certificate
export TAFFEE_REPO=demo-web                                                  # optional default for -r

taffee-mcp --help                          # commands; `taffee-mcp COMMAND --help` for a command's options
taffee-mcp repos                           # repos that are ready
taffee-mcp stats -r demo-web
taffee-mcp search "where is login handled" -r demo-web --top 3      # omit -r to search every repo
taffee-mcp node OrderService -r demo-shop
taffee-mcp path OrderService CustomerService -r demo-shop --undirected
taffee-mcp hubs -r demo-web --top 5
taffee-mcp code src/lib/api.tsx -r demo-web --from 1 --to 40
taffee-mcp tools                           # what the server offers
taffee-mcp call god_nodes repo=demo-web   # any tool, raw parameters
```

**Interactive shell** with `taffee-mcp-interactive`:
```
export MCP_URL=https://<host>:<port>/mcp MCP_TOKEN=<token> MCP_INSECURE=1
taffee-mcp-interactive
# then type:  repos
#             search "query" -r demo-web
#             path OrderService CustomerService -r demo-shop
#             quit
```

Commands: `repos stats node explain neighbors affected hubs community path query search code`, each mapping to one server tool
(shown in `taffee-mcp COMMAND --help`). Results go to stdout, so they pipe cleanly; timing (connect, handshake, the tool call) and errors go to stderr
(`-q` hides the timing). A failed call exits with status 1. There is deliberately no `--token` flag, which would end up in shell
history; use `MCP_TOKEN` or `--token-file`.

## Security, current state

- HTTPS with a self-signed certificate (set `MCP_CERT_IPS` for extra addresses). On a real deployment terminate TLS at a load
  balancer with a managed certificate.
- One token per caller, clear text on purpose for now; revoke one by deleting its line and restarting.
- Each MCP session is bound to the caller that opened it: a request on another caller's session gets 404, as for an
  unknown session. At most `MAX_SESSIONS` (10,000) sessions are tracked; the oldest are forgotten first.
- Every call is logged (caller, tool, duration, ok/refused/error), rate-limited per caller and time-limited. Exceptions that
  were not deliberately raised are replaced with a generic message before leaving the process.
- Keep Neo4j's own ports off the network; only this server knows the Neo4j password.
- Read-only data layer: The MCP service never creates, updates, or deletes data in Neo4j. All sessions across the server (`server.py`) and turbo pack data access (`turbo_data.py`, `diagnose_candidate_scores.py`) are opened with `default_access_mode="READ"` and executed within read transactions (`execute_read`). Any mutating Cypher statement (`CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`) is refused at the driver and database transaction levels with `Neo.ClientError.Statement.AccessMode`.

## Connecting an agent

Give each agent its own token from the tokens file (never paste it into chats or commit it). `gen_tokens.sh [file] [name ...]`
creates one per caller name. In any MCP client that supports the HTTP transport, add a server with the URL
`https://<host>:<port>/mcp` and the header `Authorization: Bearer <TOKEN>`. With a self-signed certificate the client must be
told to trust it. Client setup was not tested here beyond the bundled test client and `taffee-mcp`.

## Not done

Git provider adapters with the caller's own permissions (`read_code` reads a local clone), per-user permissions and audit
log, and the hardening list above.
