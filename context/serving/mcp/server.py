"""Read-only MCP front door for the code context stored in Neo4j (ContextSnapshot / ContextEntity / ContextChunk).

Implements token authentication, rate limiting, error sanitizing, token budgets, and
parameterized Cypher queries adapted for TAFFEE's Neo4j schema.

Design rules:
  * Only this process knows the Neo4j password. Clients present a bearer token.
  * Every database call is one of the fixed, parameterised queries below. No client-supplied Cypher ever reaches
    Neo4j (Community edition has no read-only users, so this is where read-only is enforced).
  * Every query is scoped to one snapshot: one repo at one commit (the newest ready one unless the caller names a
    commit). Repos never mix in a result.
  * `query_graph`, `affected`, `get_node`, `explain` and `god_nodes` run graphify's own code on a graph rebuilt from the
    original Graphify node and link objects the loader stored (nativePropertiesJson, nativeOrder), cached per repo and
    commit; snapshots never change, so nothing to invalidate. graphifyy is pinned because some helpers are private.
  * Every tool call is logged (caller, tool, duration, ok/error) to stderr, rate-limited per caller, and given a hard
    time limit. Any exception that was not deliberately raised for the caller (a plain ValueError) is replaced with a
    generic message before it leaves the process, server-side detail only in the log.
"""
import contextvars
import time
import traceback
from collections import deque
import hmac
import json
import os
import re
import subprocess
import threading
from collections import OrderedDict

from mcp.server.fastmcp import FastMCP
from neo4j import GraphDatabase

MODEL = "jinaai/jina-embeddings-v2-base-code"
# Same pinned revisions the ingestion image bakes in (context/ingestion/chunks/chunker.ts).
MODEL_REV = os.environ.get("JINA_MODEL_REV", "516f4baf13dec4ddddda8631e019b5737c8bc250")
CODE_REV = os.environ.get("JINA_CODE_REV", "3baf9e3ac750e76e8edd3019170176884695fb94")
MAX_EMBED_TOKENS = int(os.environ.get("EMBED_MAX_TOKENS", "8192"))
SEARCH_FETCH = 600  # the vector index is global across snapshots: over-fetch, then keep one snapshot's rows

driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
mcp = FastMCP("code-graph", host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "8765")))
from taffee_context.storage import Ambiguous, NotFound, open_read_store
store = open_read_store()  # the read-only view: the only storage the tools below use


# ---------------------------------------------------------------- helpers


def clamp(v, lo, hi):
    """Limit v to the range lo to hi, as an integer."""
    return max(lo, min(hi, int(v)))


def text(v, name="value", limit=300):
    """Return v stripped. Raises ValueError if it is empty or longer than limit characters."""
    v = (v or "").strip()
    if not v or len(v) > limit:
        raise ValueError(f"{name} must be 1-{limit} characters")
    return v


def sid(repo, sha):
    """The snapshot id the loader stores: JSON of [repoId, commit SHA]."""
    return json.dumps([repo, sha], separators=(",", ":"), ensure_ascii=False)


def snapshot(repo, commit=None):
    """The one (repo, commit) every query is scoped to."""
    repo = text(repo, "repo", 200)
    try:
        sha = store.resolve_snapshot(repo, text(commit, "commit", 40) if commit else None)
    except (NotFound, Ambiguous) as e:
        raise ValueError(str(e)) from None
    return repo, sha


def find_node(repo, sha, label):
    """Exact label (case-insensitive) or id; then a suffix match; then a substring match."""
    return store.find_nodes(repo, sha, text(label, "label"))


def pick(repo, sha, label):
    """Return the matches for label. Raises ValueError naming the label if there are none."""
    rows = find_node(repo, sha, label)
    if not rows:
        raise ValueError(f"nothing named '{label}' in {repo}")
    return rows


def neighbours(repo, sha, node_id, relation=None, limit=200):
    """Direct connections of a node, filtered by relation when given. Delegates to the store."""
    return store.neighbours(repo, sha, node_id, relation, limit)


def where(n):
    """Format a node's location as file:line, or just the file when there is no line."""
    f = n.get("file") or ""
    return f"{f}:{n['loc']}" if n.get("loc") and f else (f or "")


class Budget:
    """Collects output lines within a token budget, at about four characters per token."""
    def __init__(self, tokens):
        """Start with the budget, clamped to 200 to 8000 tokens."""
        self.left = clamp(tokens, 200, 8000) * 4  # ~4 characters per token
        self.lines = []

    def add(self, line):
        """Append a line if it fits and return True. Otherwise append nothing and return False."""
        if len(line) + 1 > self.left:
            return False
        self.lines.append(line)
        self.left -= len(line) + 1
        return True

    def out(self, header=""):
        """Join the accepted lines, with an optional header line first."""
        return (header + "\n" if header else "") + "\n".join(self.lines)


# ---------------------------------------------------------------- in-memory graph (graphify's own code runs on it)
GRAPH_CACHE_SIZE = int(os.environ.get("GRAPH_CACHE_SIZE", "8"))
_graphs = OrderedDict()
_graphs_lock = threading.Lock()


def build_graph(repo, sha):
    """Rebuild the graph.json graph for one snapshot from Neo4j, exactly as graphify's loader would hold it.
    The loader keeps each original node and link object (nativePropertiesJson) and its position (nativeOrder)."""
    from networkx.readwrite import json_graph
    from graphify.serve import _get_trigram_index
    data = store.read_graph(repo, sha)
    nodes, edges = data["nodes"], data["edges"]
    if any(n["p"] is None for n in nodes) or any(e["p"] is None for e in edges):
        raise ValueError("this snapshot has no native graph properties; it cannot be rebuilt")
    nodes.sort(key=lambda n: (n["ord"], n["id"]))
    edges.sort(key=lambda e: e["ord"])
    G = json_graph.node_link_graph({"directed": True, "multigraph": False, "graph": {},
                                    "nodes": [json.loads(n["p"]) for n in nodes],
                                    "links": [json.loads(e["p"]) for e in edges]}, edges="links")
    G.graph["_logical_directed"] = False
    G.graph["_learning_overlay"] = {}
    _get_trigram_index(G)  # warm the search index, as graphify's own loader does
    return G


def graph_for(repo, sha):
    """Return the in-memory graph for one snapshot, built once and kept in a cache of GRAPH_CACHE_SIZE entries."""
    key = (repo, sha)
    with _graphs_lock:
        if key in _graphs:
            _graphs.move_to_end(key)
            return _graphs[key]
    G = build_graph(repo, sha)
    with _graphs_lock:
        _graphs[key] = G
        while len(_graphs) > GRAPH_CACHE_SIZE:
            _graphs.popitem(last=False)
    return G


def node_block(G, nid):
    """Detail lines for one node: label, id, source, type, community and degree."""
    d = G.nodes[nid]
    src = f"{d.get('source_file', '')} {d.get('source_location', '')}".strip()
    return [f"Node: {d.get('label', nid)}", f"  ID: {nid}", f"  Source: {src}", f"  Type: {d.get('file_type', '')}",
            f"  Community: {d.get('community', '')}", f"  Degree: {G.degree(nid)}"]


# ---------------------------------------------------------------- identity, rate limit, logging, error sanitizing
_caller = contextvars.ContextVar("caller", default="unknown")
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))
_calls = {}
_calls_lock = threading.Lock()


def _check_rate_limit(name):
    """Record one call for this tool and caller. Raises ValueError when the per-minute limit is reached."""
    now = time.monotonic()
    with _calls_lock:
        q = _calls.setdefault(name, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT_PER_MINUTE:
            raise ValueError(f"rate limit: at most {RATE_LIMIT_PER_MINUTE} calls per minute per caller; try again shortly")
        q.append(now)


def guarded(fn):
    """Wraps every tool: attaches the caller's identity to the log, enforces the per-caller rate limit,
    times the call, and turns any exception that was not deliberately raised (a plain ValueError) into a
    generic message -- so a Neo4j or Python internal error, a query string or a stack trace never reaches
    a client. Full detail always goes to the server-side log."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        name = _caller.get()
        t = time.perf_counter()
        try:
            _check_rate_limit(name)
            result = fn(*args, **kwargs)
        except ValueError as e:
            print(f"CALL caller={name} tool={fn.__name__} ms={(time.perf_counter() - t) * 1000:.0f} "
                  f"result=refused detail={e}", flush=True)
            raise
        except Exception as e:
            print(f"CALL caller={name} tool={fn.__name__} ms={(time.perf_counter() - t) * 1000:.0f} result=error\n"
                  + traceback.format_exc(), flush=True)
            raise ValueError("internal error; ask an operator to check the server log") from None
        else:
            print(f"CALL caller={name} tool={fn.__name__} ms={(time.perf_counter() - t) * 1000:.0f} result=ok", flush=True)
            return result
    return wrapper


# ---------------------------------------------------------------- tools
@mcp.tool()
@guarded
def list_repos(query: str = "", limit: int = 25, offset: int = 0, all_commits: bool = False) -> str:
    """List repos that are ready to query, one page at a time. `query` filters by name (substring). By default each repo
    shows its newest commit; all_commits=true lists every commit. Result says how many repos matched in total."""
    q, lim, off = (query or "").strip()[:200], clamp(limit, 1, 100), max(0, int(offset))
    total, rows = store.list_repos_page(q, lim, off, all_commits)
    return json.dumps({"total": total, "offset": off, "limit": lim, "repos": rows}, indent=1, default=str)


@mcp.tool()
@guarded
def graph_stats(repo: str, commit: str = "") -> str:
    """Summary statistics for a repo: node/edge counts, communities, and how many edges were read directly vs inferred."""
    repo, sha = snapshot(repo, commit or None)
    st = store.stats(repo, sha)
    nodes, edges, chunks = st["nodes"], st["edges"], st["chunks"]
    return json.dumps({"repo": repo, "commit": sha, **nodes, "edges": sum(e["n"] for e in edges),
                       "edgeConfidence": {e["confidence"]: e["n"] for e in edges}, "chunks": chunks}, indent=1)


@mcp.tool()
@guarded
def get_node(repo: str, label: str, commit: str = "") -> str:
    """Details for a symbol or file by label or id: where it is, its type, its community and how many connections it has."""
    from graphify.serve import _find_node
    repo, sha = snapshot(repo, commit or None)
    label = text(label, "label")
    G = graph_for(repo, sha)
    ids = _find_node(G, label)
    if not ids:
        return f"[{repo} @ {sha[:10]}]\nNo node matching '{label}' found."
    return f"[{repo} @ {sha[:10]}]\n" + "\n\n".join("\n".join(node_block(G, n)) for n in ids[:5])


@mcp.tool()
@guarded
def explain(repo: str, label: str, token_budget: int = 2000, commit: str = "") -> str:
    """Plain-text explanation of one node: its details plus every connection, with direction, relation and confidence."""
    from graphify.serve import _find_node
    repo, sha = snapshot(repo, commit or None)
    label = text(label, "label")
    G = graph_for(repo, sha)
    ids = _find_node(G, label)
    if not ids:
        return f"[{repo} @ {sha[:10]}]\nNo node matching '{label}' found."
    nid = ids[0]
    conns = [("<--", u, d) for u, _, d in G.in_edges(nid, data=True)] + [("-->", v, d) for _, v, d in G.out_edges(nid, data=True)]
    conns.sort(key=lambda c: (c[2].get("relation", ""), G.nodes[c[1]].get("label", c[1]), c[0]))
    b = Budget(token_budget)
    cut = 0
    for arrow, other, d in conns:
        at = f"{d.get('source_file', '')}:{d.get('source_location', '')}" if d.get("source_location") else ""
        if not b.add(f"  {arrow} {G.nodes[other].get('label', other)} [{d.get('relation', '')}] [{d.get('confidence', '')}] {at}".rstrip()):
            cut += 1
    return (f"[{repo} @ {sha[:10]}]\n" + "\n".join(node_block(G, nid)) + f"\n\nConnections ({len(conns)}):\n" + b.out()
            + (f"\n... {cut} more cut by token_budget" if cut else ""))


@mcp.tool()
@guarded
def affected(repo: str, query: str, relations: list[str] | None = None, depth: int = 2, commit: str = "") -> str:
    """Impact analysis: what depends on this symbol or file, so what could break if it changes. Walks connections
    backwards up to `depth` steps. `relations` limits which kinds of link count (default: graphify's own set)."""
    from graphify.affected import DEFAULT_AFFECTED_RELATIONS, format_affected
    repo, sha = snapshot(repo, commit or None)
    G = graph_for(repo, sha)
    rel = tuple(r.strip() for r in relations if r.strip()) if relations else tuple(DEFAULT_AFFECTED_RELATIONS)
    return f"[{repo} @ {sha[:10]}]\n" + format_affected(G, text(query, "query"), relations=rel, depth=clamp(depth, 1, 6))


@mcp.tool()
@guarded
def get_neighbors(repo: str, label: str, relation_filter: str = "", token_budget: int = 2000, commit: str = "") -> str:
    """Everything directly connected to a node (callers, callees, imports, methods...) with the relation and confidence."""
    repo, sha = snapshot(repo, commit or None)
    node = pick(repo, sha, label)[0]
    b = Budget(token_budget)
    dropped = 0
    for n in neighbours(repo, sha, node["id"], relation_filter or None):
        arrow = "-->" if n["outgoing"] else "<--"
        if not b.add(f"{node['label']} {arrow}[{n['rel']}, {n['conf'] or '?'}] {n['label']}  {where(n)}"):
            dropped += 1
    return b.out(f"[{repo} @ {sha[:10]}] {node['kind']} {node['label']} {where(node)}") + \
        (f"\n... {dropped} more cut by token_budget" if dropped else "")


@mcp.tool()
@guarded
def god_nodes(repo: str, top_n: int = 10, commit: str = "") -> str:
    """The most-connected real entities: the core abstractions of a repo (file hubs and noise excluded, as graphify does)."""
    from graphify.analyze import god_nodes as graphify_god_nodes
    repo, sha = snapshot(repo, commit or None)
    G = graph_for(repo, sha)
    rows = graphify_god_nodes(G, clamp(top_n, 1, 50))
    lines = []
    for r in rows:
        d = G.nodes[r["id"]]
        lines.append(f"{r['degree']:>4}  {r['label']}  " + where({"file": d.get("source_file"), "loc": d.get("source_location")}))
    return f"[{repo} @ {sha[:10]}]\n" + "\n".join(lines)


@mcp.tool()
@guarded
def get_community(repo: str, community_id: int, token_budget: int = 2000, commit: str = "") -> str:
    """All nodes in one community (a cluster of related code found by graphify)."""
    repo, sha = snapshot(repo, commit or None)
    b = Budget(token_budget)
    rows = store.community_members(repo, sha, str(int(community_id)), 500)
    cut = sum(0 if b.add(f"{r['label']}  {where(r)}") else 1 for r in rows)
    return b.out(f"[{repo} @ {sha[:10]}] community {community_id}: {len(rows)} nodes") + \
        (f"\n... {cut} more cut by token_budget" if cut else "")


@mcp.tool()
@guarded
def shortest_path(repo: str, source: str, target: str, max_hops: int = 8, undirected: bool = False, commit: str = "") -> str:
    """Shortest chain of relationships between two symbols. Follows edge direction unless undirected=true."""
    repo, sha = snapshot(repo, commit or None)
    a, z = pick(repo, sha, source)[0], pick(repo, sha, target)[0]
    hops = clamp(max_hops, 1, 10)
    arrow = "-" if undirected else "->"
    rows = store.shortest_path(repo, sha, a["id"], z["id"], hops, undirected)
    if not rows:
        return f"[{repo} @ {sha[:10]}] no path from {a['label']} to {z['label']} within {hops} hops"
    names, rels, fwd = rows[0]["names"], rows[0]["rels"], rows[0]["fwd"]
    out = names[0] + "".join(f" -[{r}]-> {n}" if f else f" <-[{r}]- {n}" for r, f, n in zip(rels, fwd, names[1:]))
    return f"[{repo} @ {sha[:10]}] {len(rels)} hops\n{out}"


@mcp.tool()
@guarded
def query_graph(repo: str, question: str, mode: str = "bfs", depth: int = 3, token_budget: int = 2000,
                context_filter: list[str] | None = None, commit: str = "") -> str:
    """Search by keywords, then walk outward from the best matches (bfs = broad context, dfs = follow one trail).
    `context_filter` limits the walk to kinds of link, for example ["call", "import"]. Same engine as graphify's own tool."""
    from graphify.serve import _query_graph_text
    repo, sha = snapshot(repo, commit or None)
    G = graph_for(repo, sha)
    out = _query_graph_text(G, text(question, "question", 500), mode="dfs" if mode == "dfs" else "bfs", depth=clamp(depth, 1, 6),
                            token_budget=clamp(token_budget, 200, 8000),
                            context_filters=[c for c in (context_filter or []) if c.strip()] or None, graph_path=None)
    return f"[{repo} @ {sha[:10]}]\n" + out


_model = None
_model_lock = threading.Lock()


def embed(query):
    """Load Jina on first use (about 1 GB) and embed one query, exactly as ingestion embedded chunks (same pinned
    revisions, same token cap, offline). Loaded once and kept for the life of the process."""
    global _model
    with _model_lock:
        if _model is None:
            import torch
            from transformers import AutoModel
            torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "2")))
            _model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, revision=MODEL_REV, code_revision=CODE_REV)
        return [float(x) for x in _model.encode([query[:8000]], batch_size=1, max_length=MAX_EMBED_TOKENS)[0]]


@mcp.tool()
@guarded
def semantic_search(query: str, repo: str = "", top_k: int = 8, commit: str = "") -> str:
    """Find code by meaning ('where are failed payments retried?'). Leave repo empty to search every repo.
    Returns file and line range of each matching chunk plus the named symbols inside it."""
    query = text(query, "query", 1000)
    top_k = clamp(top_k, 1, 25)
    s = None
    if repo:
        repo, sha = snapshot(repo, commit or None)
        s = sid(repo, sha)
        state = store.semantic_state(repo, sha)
        if state != "ready":
            raise ValueError(f"the semantic layer of {repo} @ {sha[:10]} is not ready (run chunk-embed)")
    vec = embed(query)
    if s is not None:
        top = store.scoped_chunks(s, vec, top_k)
    else:
        top = store.global_chunks(vec, top_k)
    if not top:
        return "no matches"
    out = []
    for r in top:
        rp, sh = json.loads(r["snap"])
        symbols = store.chunk_symbols(r["snap"], r["id"])
        note = ""
        if r["cut"]:
            note += f"  (cut: only the first {r['emb']} of {r['chars']} characters were searched)"
        if r["tcut"]:
            note += f"  (cut: only the first {MAX_EMBED_TOKENS} tokens were searched)"
        out.append(f"{r['score']:.3f}  {rp} @ {sh[:10]}  {r['file']}:{r['s']}-{r['e']}{note}\n"
                   f"       symbols: {', '.join(symbols) or '(none)'}")
    return "\n".join(out)


# ---------------------------------------------------------------- code text (read from Git, never stored)
CODE_ROOT = os.environ.get("CODE_ROOT", "/repos")
REPO_PREFIX = os.environ.get("REPO_PREFIX", "")
READ_MAX_LINES = int(os.environ.get("READ_MAX_LINES", "400"))
_REPO_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_FILE_PATH = re.compile(r"^[A-Za-z0-9_@+.,=~ /-]+$")


@mcp.tool()
@guarded
def read_code(repo: str, file: str, start_line: int = 1, end_line: int = 0, commit: str = "") -> str:
    """Read lines of a source file exactly as committed at the snapshot's commit. Only files that were indexed can be read.
    Default is 200 lines from start_line; at most 400. Uncommitted local edits are never shown."""
    repo, sha = snapshot(repo, commit or None)
    file = text(file, "file", 400)
    if file.startswith(("/", "-")) or ".." in file.split("/") or not _FILE_PATH.match(file):
        raise ValueError("file must be a plain repo-relative path")
    if not store.file_has_entities(sid(repo, sha), file):
        raise ValueError(f"'{file}' is not an indexed file of {repo} at this commit (use get_node or semantic_search to find paths)")
    name = repo.removeprefix(REPO_PREFIX)
    if not _REPO_NAME.match(name):
        raise ValueError("repo name not readable")
    path = os.path.join(CODE_ROOT, name)
    if not os.path.isdir(path):
        raise ValueError("source for this repo is not available on this server")
    # A Git provider adapter (GitHub, GitLab, with the caller's own permissions) belongs here; this one reads a local clone.
    p = subprocess.run(["git", "-c", "safe.directory=*", "-C", path, "show", f"{sha}:{file}"], capture_output=True, timeout=20)
    if p.returncode != 0:
        raise ValueError("that file is not in the repository at this commit")
    lines = p.stdout.decode("utf-8", "replace").splitlines()
    start = max(1, int(start_line))
    end = int(end_line) if int(end_line) >= start else start + 199
    end = min(end, start + READ_MAX_LINES - 1, len(lines))
    body = "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start, end + 1))
    return f"[{repo} @ {sha[:10]}] {file} lines {start}-{end} of {len(lines)} (as committed)\n{body}"


_turbo_lock = threading.Lock()
_turbo_builder = None


def get_turbo_builder():
    global _turbo_builder
    with _turbo_lock:
        if _turbo_builder is None:
            from turbo_data import TurboDataAccess
            from turbo_builder import ContextPackBuilder
            data_access = TurboDataAccess(driver)
            _turbo_builder = ContextPackBuilder(
                data_access=data_access,
                code_root=CODE_ROOT,
                embed_fn=embed
            )
        return _turbo_builder


@mcp.tool()
@guarded
def assemble_context_pack(repo: str, task: str, max_tokens: int = 4000, commit: str = "") -> str:
    """Single-shot trusted context pack assembling architectural anchors, dependency chains,
    and committed source lines within a strict token budget."""
    builder = get_turbo_builder()
    pack = builder.build_pack(
        repo=repo,
        task=task,
        max_tokens=max_tokens,
        commit=commit or None
    )
    return json.dumps(pack, indent=1, ensure_ascii=False)


# ---------------------------------------------------------------- auth + serve
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "10000"))


class BearerAuth:
    """Pure ASGI wrapper: every request needs `Authorization: Bearer <token>`, except /healthz.
    On success, sets the caller's name (never the token) in a contextvar the whole call chain can read,
    for the call log and the rate limit -- see `guarded` above.

    It also binds each MCP session to the caller that created it. The SDK routes a request to a session by the
    `mcp-session-id` header alone and cannot know who the caller is, because authentication happens here, outside
    it. So the session id returned to a caller is recorded with that caller's name, and a request carrying a session
    id is passed on only when it comes from the same caller. Anything else gets 404, the reply the MCP spec gives
    for an unknown session, so it does not reveal that the session exists. The record is dropped when the owner
    ends the session (DELETE); the table keeps at most MAX_SESSIONS records and forgets the oldest first."""

    def __init__(self, app):
        """Wrap the ASGI application."""
        self.app = app
        self.owners = OrderedDict()  # session id (bytes) -> caller name

    async def __call__(self, scope, receive, send):
        """Answer /healthz. Reject requests without a known bearer token with 401, and requests on a session that
        another caller owns with 404; pass the rest on."""
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] == "/healthz":
            return await self._reply(send, 200, b"ok")
        headers = dict(scope["headers"])
        got = headers.get(b"authorization", b"")
        supplied = got[7:] if got[:7].lower() == b"bearer " else b""
        name = None
        for n, t in TOKENS.items():  # compare against every token; no early exit
            if hmac.compare_digest(supplied, t):
                name = n
        if name is None:
            return await self._reply(send, 401, b"unauthorized", [(b"www-authenticate", b"Bearer")])
        _caller.set(name)
        sid = headers.get(b"mcp-session-id")
        if sid is not None:
            if self.owners.get(sid) != name:
                print(f"SESSION caller={name} result=refused reason=not the session owner", flush=True)
                return await self._reply(send, 404, b"session not found")
            await self.app(scope, receive, send)
            if scope.get("method") == "DELETE":
                self.owners.pop(sid, None)
            return

        async def record_new_session(message):
            if message["type"] == "http.response.start":
                new = dict(message.get("headers", [])).get(b"mcp-session-id")
                if new is not None:
                    self.owners[new] = name
                    while len(self.owners) > MAX_SESSIONS:
                        self.owners.popitem(last=False)
            await send(message)

        return await self.app(scope, receive, record_new_session)

    @staticmethod
    async def _reply(send, status, body, extra=()):
        """Send a complete plain-text HTTP response."""
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain"), *extra]})
        await send({"type": "http.response.body", "body": body})


def _load_tokens():
    """`name token` pairs, one per line, from a file (TOKENS_FILE) and/or `name:token,name:token` in MCP_TOKENS."""
    toks = {}
    path = os.environ.get("TOKENS_FILE", "")
    if path and os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#"):
                name, tok = line.split(None, 1)
                toks[name] = tok.encode()
    for pair in os.environ.get("MCP_TOKENS", "").split(","):
        if ":" in pair:
            name, tok = pair.split(":", 1)
            if tok.strip():
                toks[name.strip()] = tok.strip().encode()
    return toks


TOKENS = _load_tokens()

if __name__ == "__main__":
    import uvicorn
    if not TOKENS:
        raise SystemExit("refusing to start: no tokens configured (an open server is never allowed)")
    print(f"tokens loaded for: {', '.join(sorted(TOKENS))}", flush=True)
    ssl_cert, ssl_key = os.environ.get("SSL_CERTFILE", ""), os.environ.get("SSL_KEYFILE", "")
    uvicorn.run(BearerAuth(mcp.streamable_http_app()), host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "8765")),
                ssl_certfile=ssl_cert or None, ssl_keyfile=ssl_key or None)
