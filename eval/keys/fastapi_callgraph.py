"""Derive structural answer keys for the FastAPI question set from Python's own parser (ast), independently of
the graph under test. Run from the root of a fastapi checkout at the pinned commit:

  python fastapi_callgraph.py callers <name> [<name> ...]     # enclosing function/method of every call site
  python fastapi_callgraph.py path <from> <to>                 # shortest call chain by name (BFS)

Calls are matched by name (f() or obj.f()), the same rule a reader of the code would use. Only the fastapi/
package is scanned (no tests, no docs_src).
"""
import ast, pathlib, sys
from collections import defaultdict, deque

calls = defaultdict(set)      # enclosing qualname -> called names
callers = defaultdict(set)    # called name -> enclosing qualnames (with file)

for p in sorted(pathlib.Path("fastapi").rglob("*.py")):
    tree = ast.parse(p.read_text())

    def walk(node, stack):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk(ch, stack + [ch.name])
                continue
            if isinstance(ch, ast.Call):
                f = ch.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if name and stack:
                    q = ".".join(stack)
                    calls[q].add(name)
                    callers[name].add(f"{p}:{q}")
            walk(ch, stack)

    walk(tree, [])


def last(q):  # function name of a qualname, ignoring nested helper names like get_request_handler.app
    return q.split(".")


if sys.argv[1] == "callers":
    for t in sys.argv[2:]:
        print(t, "<-", sorted(callers[t]))
elif sys.argv[1] == "path":
    src, dst = sys.argv[2], sys.argv[3]
    starts = [q for q in calls if q == src or q.endswith("." + src)]
    seen, dq = set(starts), deque([[s] for s in starts])
    while dq:
        path = dq.popleft()
        names = set(calls[path[-1]])
        # a nested function (outer.inner) belongs to its outer function's chain
        names |= {q for q in calls if q.startswith(path[-1] + ".")}
        for n in names:
            nxt = [q for q in calls if q == n or q.endswith("." + n) or q.startswith(path[-1] + ".")] if "." not in n else [n]
            if n == dst or any(x.endswith("." + dst) or x == dst for x in nxt if x == n):
                print(" -> ".join(path + [n])); sys.exit(0)
            for x in nxt:
                if x not in seen and (x == n or x.split(".")[-1] == n or x == n):
                    seen.add(x); dq.append(path + [x])
    print("no path")
