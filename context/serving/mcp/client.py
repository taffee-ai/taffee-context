"""taffee-mcp: command-line client for the code-graph MCP server.

  taffee-mcp repos [--json]
  taffee-mcp stats -r demo-web
  taffee-mcp search "where is login handled" -r demo-web --top 3 [--table]
  taffee-mcp node OrderService -r demo-shop
  taffee-mcp path OrderService CustomerService -r demo-shop --undirected
  taffee-mcp code src/lib/api.tsx -r demo-web --from 1 --to 40
  taffee-mcp tools
  taffee-mcp call god_nodes repo=demo-web top_n=5
  taffee-mcp shell                       # interactive prompt (default: table output)

Settings come from the environment: MCP_URL (https://host:port/mcp), MCP_TOKEN, MCP_INSECURE=1 (skip certificate
verification, for the self-signed certificate) and TAFFEE_REPO (default for -r). Read the token from the tokens file
yourself and do not paste it into chats; there is deliberately no --token flag, which would land in your shell history.

Output format: interactive prompt defaults to table, one-shot commands default to JSON (--table, --json to override).
Results go to stdout, timing and errors to stderr; a failed call exits with status 1.
"""
import argparse, asyncio, json, os, shlex, sys, time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

COMMIT = ("--commit", "commit", str, "commit SHA prefix (default: the newest ready commit)")
BUDGET = ("--budget", "token_budget", int, "token budget for the answer (default 2000)")
# name, server tool, help, positionals [(dest, type, help)], options [(flag, dest, kind, help)], repo: "required" | "optional" | None
COMMANDS = [
    ("repos", "list_repos", "list the repos that are ready", [],
     [("--query", "query", str, "filter by name"), ("--limit", "limit", int, "page size"), ("--offset", "offset", int, "skip this many"),
      ("--all-commits", "all_commits", "flag", "list every commit, not just the newest")], None),
    ("stats", "graph_stats", "node, edge, community and chunk counts", [], [], "required"),
    ("node", "get_node", "where a symbol is, its type, community and connections", [("label", str, "symbol or file name")], [], "required"),
    ("explain", "explain", "one symbol with all its connections", [("label", str, "symbol or file name")], [BUDGET], "required"),
    ("neighbors", "get_neighbors", "what is directly connected to a symbol", [("label", str, "symbol or file name")],
     [("--relation", "relation_filter", str, "only this relation, for example imports or calls"), BUDGET], "required"),
    ("affected", "affected", "impact analysis: what depends on a symbol", [("query", str, "symbol or file name")],
     [("--relation", "relations", "append", "count only this kind of link (repeatable)"), ("--depth", "depth", int, "steps to walk back (default 2)")], "required"),
    ("hubs", "god_nodes", "the most-connected entities", [], [("--top", "top_n", int, "how many (default 10)")], "required"),
    ("community", "get_community", "everything in one community", [("community_id", int, "community number")], [BUDGET], "required"),
    ("path", "shortest_path", "shortest chain of relationships between two symbols",
     [("source", str, "start symbol"), ("target", str, "end symbol")],
     [("--hops", "max_hops", int, "give up after this many hops (default 8)"), ("--undirected", "undirected", "flag", "ignore edge direction")], "required"),
    ("query", "query_graph", "keyword search, then walk outward from the best matches", [("question", str, "what to look for")],
     [("--mode", "mode", ("bfs", "dfs"), "bfs for broad context, dfs to follow one trail"), ("--depth", "depth", int, "how far to walk (default 3)"),
      ("--filter", "context_filter", "append", "limit the walk to a kind of link, for example call (repeatable)"), BUDGET], "required"),
    ("search", "semantic_search", "find code by meaning (leave out -r to search every repo)", [("query", str, "what you are looking for")],
     [("--top", "top_k", int, "how many results (default 8)")], "optional"),
    ("code", "read_code", "read committed source lines of an indexed file", [("file", str, "repo-relative path")],
     [("--from", "start_line", int, "first line (default 1)"), ("--to", "end_line", int, "last line (default 200 lines on)")], "required"),
    ("pack", "assemble_context_pack", "single-shot context pack with anchors, dependency chain and code evidence",
     [("task", str, "developer task or query")],
     [("--max-tokens", "max_tokens", int, "hard token ceiling (500-16000, default 4000)")], "required"),
]


def format_table_repos(data):
    """Format repos list_repos JSON as a table."""
    if not isinstance(data, dict) or 'repos' not in data:
        return None
    repos = data.get('repos', [])
    if not repos:
        return "No repos"
    lines = [f"{'Repo':<30} {'Commit':<10} {'Entities':>8} {'Edges':>8} {'Chunks':>8} {'Semantic':<8}"]
    lines.append("-" * 80)
    for r in repos:
        entities = r.get('entities') or 0
        edges = r.get('edges') or 0
        chunks = r.get('chunks') or 0
        semantic = r.get('semantic') or 'unknown'
        lines.append(f"{r.get('repo', ''):<30} {str(r.get('commit', ''))[:10]:<10} {entities:>8.0f} "
                     f"{edges:>8.0f} {chunks:>8} {semantic:<8}")
    return "\n".join(lines)


def format_table_stats(data):
    """Format graph_stats counts as a table."""
    if not isinstance(data, dict):
        return None
    lines = []
    for key, value in data.items():
        val = value or 0 if isinstance(value, (int, float)) else value or 'N/A'
        lines.append(f"{key:<20} {val:>10}")
    return "\n".join(lines) if lines else None


def format_table_search(data):
    """Format semantic_search results as a table."""
    if not isinstance(data, (dict, list)):
        return None
    if isinstance(data, dict) and 'results' in data:
        results = data.get('results', [])
    elif isinstance(data, list):
        results = data
    else:
        return None
    if not results:
        return "No results"
    lines = [f"{'File':<40} {'Score':>8} {'Location':<30}"]
    lines.append("-" * 80)
    for r in results:
        if not isinstance(r, dict):
            continue
        file_path = r.get('file') or r.get('path') or 'unknown'
        score = r.get('score') or r.get('similarity') or 0
        line_range = r.get('line') or r.get('lines') or ''
        location = f"{line_range}" if line_range else "N/A"
        lines.append(f"{str(file_path)[:40]:<40} {score:>8.3f} {location:<30}")
    return "\n".join(lines) if len(lines) > 2 else None


def format_table_hubs(data):
    """Format god_nodes results as a table."""
    if not isinstance(data, (dict, list)):
        return None
    if isinstance(data, dict) and 'nodes' in data:
        nodes = data.get('nodes', [])
    elif isinstance(data, dict) and 'results' in data:
        nodes = data.get('results', [])
    elif isinstance(data, list):
        nodes = data
    else:
        return None
    if not nodes:
        return "No hubs"
    lines = [f"{'Entity':<35} {'Connections':>12} {'Type':<15}"]
    lines.append("-" * 65)
    for n in nodes:
        if not isinstance(n, dict):
            continue
        name = n.get('label') or n.get('name') or 'unknown'
        conn = n.get('connections') or n.get('degree') or 0
        typ = n.get('type') or n.get('entity_type') or 'entity'
        lines.append(f"{str(name)[:35]:<35} {conn:>12} {typ:<15}")
    return "\n".join(lines) if len(lines) > 2 else None


def format_table_neighbors(data):
    """Format get_neighbors results as a table."""
    if not isinstance(data, (dict, list)):
        return None
    if isinstance(data, dict) and 'neighbors' in data:
        neighbors = data.get('neighbors', [])
    elif isinstance(data, list):
        neighbors = data
    else:
        return None
    if not neighbors:
        return "No neighbors"
    lines = [f"{'Entity':<35} {'Relation':<20} {'Type':<15}"]
    lines.append("-" * 70)
    for n in neighbors:
        if not isinstance(n, dict):
            continue
        label = n.get('label') or n.get('name') or 'unknown'
        rel = n.get('relation') or n.get('type') or 'unknown'
        typ = n.get('entity_type') or 'entity'
        lines.append(f"{str(label)[:35]:<35} {str(rel)[:20]:<20} {typ:<15}")
    return "\n".join(lines) if len(lines) > 2 else None


def format_table_affected(data):
    """Format affected results as a table."""
    if not isinstance(data, (dict, list)):
        return None
    if isinstance(data, dict) and 'affected' in data:
        affected = data.get('affected', [])
    elif isinstance(data, list):
        affected = data
    else:
        return None
    if not affected:
        return "Nothing affected"
    lines = [f"{'Entity':<35} {'Relation':<20} {'Depth':>6}"]
    lines.append("-" * 62)
    for a in affected:
        if not isinstance(a, dict):
            continue
        label = a.get('label') or a.get('name') or 'unknown'
        rel = a.get('relation') or a.get('type') or 'depends-on'
        depth = a.get('depth') or 0
        lines.append(f"{str(label)[:35]:<35} {str(rel)[:20]:<20} {depth:>6}")
    return "\n".join(lines) if len(lines) > 2 else None


def format_table_path(data):
    """Format shortest_path results as a table."""
    if not isinstance(data, (dict, list)):
        return None
    if isinstance(data, dict):
        if 'path' in data:
            path = data.get('path', [])
        elif 'nodes' in data:
            path = data.get('nodes', [])
        else:
            return None
    elif isinstance(data, list):
        path = data
    else:
        return None
    if not path:
        return "No path found"
    path_str = " -> ".join(str(node.get('label') if isinstance(node, dict) else node) for node in path)
    return path_str


def format_table_pack(data):
    """Format assemble_context_pack JSON as a clean terminal table showing anchors, dependency chain, and code evidence."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None

    meta = data.get("metadata", {})
    ba = data.get("budget_accounting", {})
    val = data.get("validation", {})
    anchors = data.get("architectural_anchors", [])
    deps = data.get("dependency_chain", [])
    evidence = data.get("code_evidence", [])

    lines = []
    repo = meta.get("repoId", "unknown")
    sha = str(meta.get("commitSHA", ""))[:10]
    task = meta.get("requestedTask", "")
    lines.append(f"Context Pack: {repo} @ {sha}")
    lines.append(f"Task: {task}")
    lines.append(f"Tokens: {ba.get('consumed_tokens', 0)} / {ba.get('requested_tokens', 0)} (truncated: {ba.get('truncated', False)}) | Confidence: {ba.get('confidence_score', 0.0)}")
    lines.append(f"Validation: status={val.get('status', 'pass')} score={val.get('score', 0.0)}")
    lines.append("")

    lines.append("=== ARCHITECTURAL ANCHORS ===")
    if anchors:
        lines.append(f"{'Label':<30} {'Type':<12} {'Location':<35} {'Degree':>6} {'Score':>6}")
        lines.append("-" * 95)
        for a in anchors:
            lbl = str(a.get("label", ""))[:30]
            typ = str(a.get("type", ""))[:12]
            loc = str(a.get("location", ""))[:35]
            deg = a.get("degree", 0)
            score = a.get("hybridScore", 0.0)
            lines.append(f"{lbl:<30} {typ:<12} {loc:<35} {deg:>6} {score:>6.2f}")
    else:
        lines.append("No anchors included")
    lines.append("")

    lines.append("=== DEPENDENCY CHAIN ===")
    if deps:
        lines.append(f"{'From':<30} {'Relation':<15} {'To':<30} {'Conf':<10}")
        lines.append("-" * 88)
        for d in deps:
            frm = str(d.get("from", ""))[:30]
            rel = str(d.get("relation", ""))[:15]
            to = str(d.get("to", ""))[:30]
            conf = str(d.get("confidence", ""))[:10]
            lines.append(f"{frm:<30} {rel:<15} {to:<30} {conf:<10}")
    else:
        lines.append("No dependency edges included")
    lines.append("")

    lines.append("=== CODE EVIDENCE SUMMARY ===")
    if evidence:
        lines.append(f"{'File':<40} {'Lines':<15} {'Kept/Orig':>10} {'Chunk ID':<20}")
        lines.append("-" * 90)
        for ce in evidence:
            f = str(ce.get("file", ""))[:40]
            loc = f"L{ce.get('startLine')}-L{ce.get('endLine')}"
            kept = f"{ce.get('kept_lines', 0)}/{ce.get('original_lines', 0)}"
            cid = str(ce.get("chunkId", ""))[:20]
            lines.append(f"{f:<40} {loc:<15} {kept:>10} {cid:<20}")
    else:
        lines.append("No code evidence included")

    return "\n".join(lines)


def format_json_or_table(data, use_table, command_name):
    """Format output as JSON or table based on preference and command type."""
    if use_table in (False, "json", None):
        return json.dumps(data, indent=1)
    if use_table not in (True, "table"):
        return json.dumps(data, indent=1)
    # Try command-specific table formatting
    formatters = {
        "repos": format_table_repos,
        "stats": format_table_stats,
        "search": format_table_search,
        "hubs": format_table_hubs,
        "neighbors": format_table_neighbors,
        "affected": format_table_affected,
        "path": format_table_path,
        "pack": format_table_pack,
    }
    formatter = formatters.get(command_name)
    if formatter:
        table = formatter(data)
        if table:
            return table
    return json.dumps(data, indent=1)  # Fallback to JSON


def parse_call(tokens):
    """`TOOL key=value ...` or `TOOL '{json}'` to (tool, arguments). A value is JSON when it parses as JSON, else text."""
    if not tokens:
        raise ValueError("empty call")
    name, rest = tokens[0], tokens[1:]
    if len(rest) == 1 and rest[0].lstrip().startswith("{"):
        return name, json.loads(rest[0])
    args = {}
    for item in rest:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(f"expected key=value, got {item!r}")
        try:
            args[key] = json.loads(value)
        except json.JSONDecodeError:
            args[key] = value
    return name, args


def add_option(p, flag, dest, kind, help):
    if kind == "flag":
        p.add_argument(flag, dest=dest, action="store_true", default=None, help=help)
    elif kind == "append":
        p.add_argument(flag, dest=dest, action="append", help=help)
    elif isinstance(kind, tuple):
        p.add_argument(flag, dest=dest, choices=kind, help=help)
    else:
        p.add_argument(flag, dest=dest, type=kind, help=help)


def build_parser(is_interactive=False):
    ap = argparse.ArgumentParser(prog="taffee-mcp", description="Command-line client for the code-graph MCP server.",
                                 epilog="Set MCP_URL and MCP_TOKEN (and MCP_INSECURE=1 for a self-signed certificate). "
                                        "Use `taffee-mcp COMMAND --help` for a command's options.")
    ap.add_argument("--url", default=os.environ.get("MCP_URL"), help="server URL, https://host:port/mcp (default: $MCP_URL)")
    ap.add_argument("--token-file", help="read the token from this file instead of $MCP_TOKEN")
    ap.add_argument("--insecure", action="store_true", default=os.environ.get("MCP_INSECURE") == "1",
                    help="skip certificate verification, for a self-signed certificate (default: $MCP_INSECURE=1)")
    ap.add_argument("-q", "--quiet", action="store_true", help="do not print timing")
    ap.add_argument("--table", dest="format", action="store_const", const="table", help="output as table (interactive default)")
    ap.add_argument("--json", dest="format", action="store_const", const="json", help="output as JSON (one-shot default)")
    sub = ap.add_subparsers(dest="command", metavar="command", required=True)
    for name, tool, help, positionals, options, repo in COMMANDS:
        p = sub.add_parser(name, help=f"{help}  [{tool}]", description=f"{help} (server tool: {tool})")
        dests = [d for d, _, _ in positionals] + [o[1] for o in options]
        for dest, typ, h in positionals:
            p.add_argument(dest, type=typ, help=h)
        if repo:
            p.add_argument("-r", "--repo", default=os.environ.get("TAFFEE_REPO"),
                           help="repository" + (" (required)" if repo == "required" else "") + "; default: $TAFFEE_REPO")
            dests = ["repo"] + dests
        for flag, dest, kind, h in options + ([COMMIT] if repo else []):
            add_option(p, flag, dest, kind, h)
        if repo:
            dests.append("commit")
        p.add_argument("--table", dest="format", action="store_const", const="table", help="output as table")
        p.add_argument("--json", dest="format", action="store_const", const="json", help="output as JSON")
        p.set_defaults(tool=tool, repo_mode=repo, dests=dests)
    sub.add_parser("tools", help="list the server's tools and their parameters")
    c = sub.add_parser("call", help="call any tool by name: call TOOL key=value ... (or one JSON object)")
    c.add_argument("tool_name")
    c.add_argument("params", nargs="*")
    sub.add_parser("shell", help="open a prompt that keeps one session open; type the same commands without 'taffee-mcp'")
    return ap


def client_factory(insecure):
    def make(headers=None, timeout=None, auth=None):
        kw = {"follow_redirects": True, "timeout": timeout or httpx.Timeout(60.0), "verify": not insecure}
        if headers is not None:
            kw["headers"] = headers
        if auth is not None:
            kw["auth"] = auth
        return httpx.AsyncClient(**kw)
    return make


async def show_tools(s):
    for t in (await s.list_tools()).tools:
        schema = t.inputSchema or {}
        required = set(schema.get("required", []))
        print(f"  {t.name}({', '.join(k + ('' if k in required else '?') for k in schema.get('properties', {}))})")


def cmd_help(cmd_name):
    """Print help for a specific command."""
    for name, tool, help_text, positionals, options, repo in COMMANDS:
        if name == cmd_name:
            print(f"{name}: {help_text}")
            print(f"  server tool: {tool}")
            if positionals:
                print("  positional arguments:")
                for dest, typ, h in positionals:
                    print(f"    {dest:<20} {h}")
            if options:
                print("  options:")
                for flag, dest, kind, h in options:
                    print(f"    {flag:<20} {h}")
            if repo:
                print(f"  repository:          {'required' if repo == 'required' else 'optional'}")
            return
    print(f"Unknown command: {cmd_name}. Type 'tools' to see all commands.")


async def run(s, ns):
    """Runs one parsed command. Returns (exit status, milliseconds spent in the tool call)."""
    if ns.command == "tools":
        await show_tools(s)
        return 0, 0.0
    if ns.command == "call":
        try:
            name, args = parse_call([ns.tool_name] + ns.params)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2, 0.0
    else:
        if ns.repo_mode == "required" and not ns.repo:
            print("error: -r/--repo is required (or set TAFFEE_REPO)", file=sys.stderr)
            return 2, 0.0
        name, args = ns.tool, {d: getattr(ns, d) for d in ns.dests if getattr(ns, d) is not None}
    t = time.perf_counter()
    try:
        res = await s.call_tool(name, args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1, (time.perf_counter() - t) * 1000
    text = "\n".join(c.text for c in res.content if hasattr(c, "text"))
    # Try to parse as JSON for formatting
    try:
        data = json.loads(text)
        use_table = getattr(ns, 'format', None)
        if use_table is None:  # Not explicitly set, use default for this mode
            use_table = getattr(ns, 'is_interactive', False)
        formatted = format_json_or_table(data, use_table, ns.command if ns.command != 'call' else name)
        print(formatted, file=sys.stderr if res.isError else sys.stdout)
    except (json.JSONDecodeError, ValueError):
        print(text, file=sys.stderr if res.isError else sys.stdout)
    return (1 if res.isError else 0), (time.perf_counter() - t) * 1000


def timing(connect, handshake, call):
    return (f"\n--- timing (ms) ---\nconnect (TCP/TLS to the server): {connect:8.0f}\nMCP session handshake:         {handshake:8.0f}\n"
            f"the tool call:                 {call:8.0f}\ntotal:                         {connect + handshake + call:8.0f}")


async def main(ap, ns):
    if not ns.url:
        ap.error("no server URL: set MCP_URL or pass --url")
    token = open(ns.token_file).read().strip() if ns.token_file else os.environ.get("MCP_TOKEN")
    if not token:
        ap.error("no token: set MCP_TOKEN or pass --token-file")
    if getattr(ns, "repo_mode", None) == "required" and not ns.repo:
        ap.error("-r/--repo is required (or set TAFFEE_REPO)")
    t0 = time.perf_counter()
    async with streamablehttp_client(ns.url, headers={"Authorization": "Bearer " + token}, httpx_client_factory=client_factory(ns.insecure)) as (r, w, _):
        t_connect = time.perf_counter()
        async with ClientSession(r, w) as s:
            await s.initialize()
            connect_ms, handshake_ms = (t_connect - t0) * 1000, (time.perf_counter() - t_connect) * 1000
            if ns.command != "shell":
                ns.is_interactive = False
                status, call_ms = await run(s, ns)
                if not ns.quiet and ns.command != "tools":
                    print(timing(connect_ms, handshake_ms, call_ms), file=sys.stderr)
                return status
            interactive = sys.stdin.isatty()
            if interactive:
                print(f"connected in {connect_ms:.0f} ms, handshake {handshake_ms:.0f} ms; type a command (help, quit)", file=sys.stderr)
            while True:
                try:
                    line = (await asyncio.to_thread(input, "taffee-mcp> " if interactive else "")).strip()
                except EOFError:
                    return 0
                if not line:
                    continue
                if line in ("quit", "exit"):
                    return 0
                if line == "help":
                    ap.print_help()
                    continue
                if line.split()[0] == "help" and len(line.split()) > 1:
                    cmd_help(line.split()[1])
                    continue
                try:
                    inner = build_parser(is_interactive=True).parse_args(["--url", ns.url] + shlex.split(line))
                    inner.is_interactive = True
                    inner.format = inner.format or ("table" if interactive else "json")  # Default based on mode
                except SystemExit:
                    continue
                if inner.command == "shell":
                    continue
                _, call_ms = await run(s, inner)
                if not ns.quiet:
                    print(f"[{call_ms:.0f} ms]", file=sys.stderr)


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.format = args.format or ("json")  # One-shot default
    try:
        sys.exit(asyncio.run(main(parser, args)))
    except Exception as e:
        cause = e
        while isinstance(cause, BaseExceptionGroup):
            cause = cause.exceptions[0]
        if isinstance(cause, httpx.ConnectError):
            sys.exit(f"could not connect to {args.url}: is the server running and reachable from here?")
        if isinstance(cause, httpx.TimeoutException):
            sys.exit(f"timed out talking to {args.url}: the server may still be starting, or a first call (cold caches, model load) is slow")
        if isinstance(cause, httpx.HTTPStatusError):
            code = cause.response.status_code
            sys.exit("the server rejected the token (401): fetch a current one" if code == 401 else f"the server answered HTTP {code}")
        raise
