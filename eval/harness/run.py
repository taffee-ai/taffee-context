"""Evaluation harness: four tool conditions on the same model. See eval/DESIGN.md.

  C0  no tools          C1  file search (grep, read_file, glob)
  C2  graph tools       C3  file search + graph tools

The harness implements every tool the agent can call, so the agent has no other access (no shell, no other
paths). Each run is one JSON line: every tool call and the tokens it returned, the model's own usage counts,
timing, the final answer and the grade. Explanatory (rubric) answers are graded by a separate judge model that
sees only the question, the rubric and the answer.

Environment: CI_BASE_URL, CI_API_KEY (model endpoint), MCP_URL, MCP_TOKEN (C2/C3).
"""
import argparse, asyncio, fnmatch, json, os, random, re, sys, time
from pathlib import Path

import httpx
import tiktoken

ENC = tiktoken.get_encoding("o200k_base")
MAX_TURNS = 14
READ_MAX_LINES, GREP_MAX, GLOB_MAX, LIST_MAX = 2000, 100, 200, 500
EXCLUDED_GRAPH_TOOLS = {"assemble_context_pack", "list_repos"}  # no pack (MCP-Turbo); the repo is fixed
CONDITIONS = {"C0": (False, False), "C1": (True, False), "C2": (False, True), "C3": (True, True)}  # (files, graph)

SYSTEM = (
    "You answer questions about the source code of the repository '{repo}' at a fixed commit. "
    "{how} Be efficient. "
    "When you are confident, reply with a short answer that ends with one JSON object on its own line: "
    '{{"files": ["<repo-relative path>", ...], "symbols": ["<function or class name>", ...]}}'
)
HOW_TOOLS = "Use the tools to find the answer in the code; do not guess without checking."
# C0 only: with the tools sentence and no tools, models write fake tool calls instead of answering (dry run,
# see VALIDATION.md), so C0 states that there are no tools. Everything else in the prompt is identical.
HOW_NO_TOOLS = "You have no tools: answer from what you already know about this repository."

JUDGE = (
    "You grade an answer to a question about a code base against a rubric. For each rubric point, decide whether "
    "the answer states it (paraphrase is fine; an answer that contradicts the point, or only hints at it vaguely, "
    "does not cover it). Reply with JSON only: {\"covered\": [true|false, ...], \"reasons\": [\"...\", ...]}, "
    "one entry per point, in order."
)


def ntok(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


# ---------- file tools (C1, C3), confined to the checkout ----------
class FileTools:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _p(self, rel: str) -> Path:
        p = (self.root / (rel or ".")).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError("path outside the repository")
        return p

    def _files(self):
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and ".git" not in p.relative_to(self.root).parts:
                yield p

    def list_dir(self, path: str = ".") -> str:
        rows = [e.name + ("/" if e.is_dir() else "") for e in sorted(self._p(path).iterdir()) if e.name != ".git"]
        return "\n".join(rows[:LIST_MAX]) + ("\n[truncated]" if len(rows) > LIST_MAX else "")

    def glob(self, pattern: str) -> str:
        rows = [str(p.relative_to(self.root)) for p in self._files() if fnmatch.fnmatch(str(p.relative_to(self.root)), pattern)]
        if not rows:
            return "no matches"
        return "\n".join(rows[:GLOB_MAX]) + ("\n[truncated]" if len(rows) > GLOB_MAX else "")

    def grep(self, pattern: str, file_glob: str = "*") -> str:
        rx, out = re.compile(pattern), []
        for p in self._files():
            rel = str(p.relative_to(self.root))
            if not fnmatch.fnmatch(rel, file_glob) or p.stat().st_size > 1_000_000:
                continue
            try:
                for i, line in enumerate(p.read_text(errors="strict").splitlines(), 1):
                    if rx.search(line):
                        out.append(f"{rel}:{i}: {line.strip()[:200]}")
                        if len(out) >= GREP_MAX:
                            return "\n".join(out) + "\n[truncated]"
            except (UnicodeDecodeError, OSError):
                continue
        return "\n".join(out) if out else "no matches"

    def read_file(self, path: str, start_line: int = 1, end_line: int = 0) -> str:
        lines = self._p(path).read_text(errors="replace").splitlines()
        start = max(1, int(start_line))
        end = min(len(lines), int(end_line) if end_line else len(lines), start + READ_MAX_LINES - 1)
        return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))

    SCHEMAS = [
        {"name": "list_dir", "description": "List a directory (repo-relative).",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
        {"name": "glob", "description": "Find files whose repo-relative path matches a glob, e.g. 'fastapi/**/*.py'.",
         "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
        {"name": "grep", "description": f"Regex search over file contents; returns path:line: text (max {GREP_MAX}).",
         "parameters": {"type": "object", "properties": {"pattern": {"type": "string"},
                                                          "file_glob": {"type": "string", "description": "e.g. '*.py'"}},
                        "required": ["pattern"]}},
        {"name": "read_file", "description": f"Read a file with line numbers (max {READ_MAX_LINES} lines per call).",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"},
                                                          "end_line": {"type": "integer"}}, "required": ["path"]}},
    ]


def graph_schemas(tools) -> list[dict]:
    out = []
    for t in tools:
        if t.name in EXCLUDED_GRAPH_TOOLS:
            continue
        schema = json.loads(json.dumps(t.inputSchema or {"type": "object", "properties": {}}))
        for k in ("repo", "commit"):
            schema.get("properties", {}).pop(k, None)
            if k in schema.get("required", []):
                schema["required"].remove(k)
        out.append({"name": t.name, "description": (t.description or "")[:1000], "parameters": schema})
    return out


# ---------- model ----------
async def chat(client, model, messages, tools, temperature=0.3, max_tokens=2048):
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        body["tools"] = [{"type": "function", "function": s} for s in tools]
    for attempt in range(7):
        try:
            r = await client.post("/chat/completions", json=body)
        except httpx.HTTPError:
            await asyncio.sleep(2 ** attempt + random.random()); continue
        if r.status_code in (429, 500, 502, 503, 504):
            await asyncio.sleep(2 ** attempt + random.random()); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"model call failed after retries (last status {r.status_code})")


# ---------- grading ----------
def parse_answer(text: str) -> dict:
    for m in reversed(list(re.finditer(r"\{[^{}]*\"files\"[^{}]*\}|\{[^{}]*\"symbols\"[^{}]*\}", text or "", re.S))):
        try:
            d = json.loads(m.group())
            return {"files": [str(f).strip().lstrip("./") for f in d.get("files", [])],
                    "symbols": [str(s).strip() for s in d.get("symbols", [])]}
        except json.JSONDecodeError:
            continue
    return {"files": [], "symbols": []}


def segments(name: str) -> set[str]:
    return {s for s in re.split(r"[.:\s()]+", name) if s}


def sym_hit(key: str, named: list[str]) -> bool:
    """Exact name match; a dotted key (Class.method) needs all its parts, a plain key matches any segment."""
    kparts = key.split(".")
    for n in named:
        segs = segments(n)
        if all(k in segs for k in kparts) if len(kparts) > 1 else key in segs:
            return True
    return False


def grade(task: dict, ans: dict, judge_cov: float | None) -> tuple[str, float, dict]:
    key, t = task["key"], task["type"]
    detail = {}
    if t == "lookup":
        files_ok = all(any(a.endswith(k) for a in ans["files"]) for k in key["files"])
        syms_ok = all(sym_hit(k, ans["symbols"]) for k in key["symbols"])
        any_file = any(any(a.endswith(k) for a in ans["files"]) for k in key["files"])
        g = "correct" if files_ok and syms_ok else "partial" if any_file else "wrong"
    elif t in ("set", "chain"):
        hits = [k for k in key["symbols"] if sym_hit(k, ans["symbols"])]
        extras = [n for n in ans["symbols"] if not any(sym_hit(k, [n]) for k in key["symbols"])]
        recall = len(hits) / len(key["symbols"])
        precision = len(hits) / len(ans["symbols"]) if ans["symbols"] else 0.0
        detail = {"recall": round(recall, 3), "precision": round(precision, 3), "extras": extras}
        if t == "chain":
            order = [k for n in ans["symbols"] for k in key["symbols"] if sym_hit(k, [n])]
            detail["order_ok"] = order == [k for k in key["symbols"] if k in order] and len(order) == len(key["symbols"])
        g = "correct" if recall == 1 and len(extras) <= 1 else "partial" if recall >= 0.5 else "wrong"
    elif t == "rubric":
        detail = {"coverage": judge_cov}
        g = "error" if judge_cov is None else "correct" if judge_cov >= 0.8 else "partial" if judge_cov >= 0.5 else "wrong"
    else:
        raise ValueError(t)
    return g, {"correct": 1.0, "partial": 0.5, "wrong": 0.0}.get(g, 0.0), detail


async def judge(client, model, task, answer_text):
    pts = task["key"]["points"]
    user = (f"Question:\n{task['question']}\n\nRubric points:\n" + "\n".join(f"{i + 1}. {p}" for i, p in enumerate(pts))
            + f"\n\nAnswer to grade:\n{answer_text}")
    resp = await chat(client, model, [{"role": "system", "content": JUDGE}, {"role": "user", "content": user}],
                      None, temperature=0.0, max_tokens=1500)
    text = resp["choices"][0]["message"].get("content") or ""
    m = re.search(r"\{.*\}", text, re.S)
    d = json.loads(m.group()) if m else {}
    cov = d.get("covered", [])
    if len(cov) != len(pts):
        return None, d, resp.get("usage") or {}
    return sum(bool(c) for c in cov) / len(pts), d, resp.get("usage") or {}


def retrieval_stats(calls: list[dict], task: dict) -> dict:
    total = sum(c["result_tokens"] for c in calls)
    key = task["key"]
    if task["type"] == "rubric":
        return {"retrieved_tokens": total, "signal_tokens": None, "signal_ratio": None, "found": None}
    files, syms = key.get("files", []), [s.split(".")[-1] for s in key.get("symbols", [])]
    signal, found_syms, found = 0, set(), False
    for c in calls:
        text = c["_text"]
        if files:
            if c.get("target_file") and any(c["target_file"].endswith(k) for k in files):
                signal += c["result_tokens"]; hit_file = True
            else:
                signal += sum(ntok(l) for l in text.splitlines() if any(k in l for k in files))
                hit_file = any(k in text for k in files)
            if hit_file and all(re.search(rf"\b{re.escape(s)}\b", text) for s in syms):
                found = True
        else:
            signal += sum(ntok(l) for l in text.splitlines() if any(re.search(rf"\b{re.escape(s)}\b", l) for s in syms))
            found_syms |= {s for s in syms if re.search(rf"\b{re.escape(s)}\b", text)}
    if not files:
        found = bool(syms) and found_syms == set(syms)
    return {"retrieved_tokens": total, "signal_tokens": signal,
            "signal_ratio": round(signal / total, 3) if total else None, "found": found}


# ---------- one run ----------
async def run_one(task, model, cond, args, http, session, gschemas, files):
    use_files, use_graph = CONDITIONS[cond]
    fschemas = [s for s in FileTools.SCHEMAS if s["name"] in args.file_tools.split(",")]
    tools = (fschemas if use_files else []) + (gschemas if use_graph else [])
    fnames, gnames = {s["name"] for s in fschemas}, {s["name"] for s in gschemas}
    how = HOW_TOOLS if tools else HOW_NO_TOOLS
    messages = [{"role": "system", "content": SYSTEM.format(repo=args.repo, how=how)}, {"role": "user", "content": task["question"]}]
    calls, usage = [], {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
    t0, final, turns, error, capped, tool_seconds = time.monotonic(), "", 0, None, False, 0.0
    try:
        while True:
            last = turns >= MAX_TURNS
            if last:
                capped = True
                messages.append({"role": "user", "content": "Turn limit reached. Give your final answer now with the JSON line."})
            resp = await chat(http, model, messages, None if (last or not tools) else tools)
            u = resp.get("usage") or {}
            usage["prompt_tokens"] += u.get("prompt_tokens", 0)
            usage["completion_tokens"] += u.get("completion_tokens", 0)
            usage["cached_tokens"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
            msg = resp["choices"][0]["message"]
            tcs = msg.get("tool_calls") or []
            messages.append({"role": "assistant", "content": msg.get("content") or "", **({"tool_calls": tcs} if tcs else {})})
            if not tcs or last or not tools:
                final = msg.get("content") or ""
                break
            turns += 1
            for tc in tcs:
                name = tc["function"]["name"]
                try:
                    a = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    a = {}
                s = time.monotonic()
                try:
                    if use_files and name in fnames:
                        text = getattr(files, name)(**a)
                    elif use_graph and name in gnames:
                        r = await session.call_tool(name, {**a, "repo": args.repo})
                        text = "\n".join(getattr(c, "text", "") for c in r.content)
                    else:
                        raise ValueError(f"unknown tool {name}")
                except Exception as e:  # tool errors go back to the agent, as a real client would do
                    text = f"error: {e}"
                tool_seconds += time.monotonic() - s
                target = a.get("path") if name == "read_file" else a.get("file") if name == "read_code" else None
                calls.append({"tool": name, "args": a, "result_tokens": ntok(text), "target_file": target, "_text": text})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": text})
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    ans = parse_answer(final)
    judge_cov, judge_raw, judge_usage = None, None, None
    if task["type"] == "rubric" and not error:
        try:
            judge_cov, judge_raw, judge_usage = await judge(http, args.judge_model, task, final)
        except Exception as e:
            judge_raw = {"error": f"{type(e).__name__}: {e}"}
    g, score, detail = grade(task, ans, judge_cov) if not error else ("error", 0.0, {})
    rec = {"task": task["id"], "category": task["category"], "type": task["type"], "model": model, "condition": cond,
           "repo": args.repo, "commit": args.commit, "turns": turns, "capped": capped, "tool_calls": len(calls),
           "seconds": round(time.monotonic() - t0, 2), "tool_seconds": round(tool_seconds, 2), "usage": usage,
           "answer": ans, "final_text": final[-4000:], "grade": g, "score": score, "grade_detail": detail,
           "judge": judge_raw, "judge_usage": judge_usage, "error": error, **retrieval_stats(calls, task)}
    rec["calls"] = [{k: v for k, v in c.items() if k != "_text"} for c in calls]
    return rec


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True); ap.add_argument("--repo", required=True)
    ap.add_argument("--commit", default=""); ap.add_argument("--checkout", required=True)
    ap.add_argument("--models", required=True); ap.add_argument("--conditions", default="C0,C1,C2,C3")
    ap.add_argument("--runs", type=int, default=3); ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated task ids"); ap.add_argument("--out", required=True)
    ap.add_argument("--file-tools", default="read_file,grep,glob")
    ap.add_argument("--judge-model", default="claude-sonnet-5.5"); ap.add_argument("--seed", type=int, default=20261114)
    args = ap.parse_args()

    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    if args.only:
        tasks = [t for t in tasks if t["id"] in args.only.split(",")]
    if Path(args.checkout).resolve() in Path(args.tasks).resolve().parents:
        raise SystemExit("answer keys are inside the checkout the agent can read")
    files = FileTools(args.checkout)
    conds = args.conditions.split(",")
    jobs = [(t, m, c) for t in tasks for m in args.models.split(",") for c in conds for _ in range(args.runs)]
    random.Random(args.seed).shuffle(jobs)
    print(f"jobs={len(jobs)} seed={args.seed}", flush=True)

    headers = {"Authorization": f"Bearer {os.environ['CI_API_KEY']}"}
    async with httpx.AsyncClient(base_url=os.environ["CI_BASE_URL"], headers=headers, timeout=240) as http:
        async def execute(session, gschemas):
            sem, out = asyncio.Semaphore(args.workers), open(args.out, "a")

            async def go(job):
                async with sem:
                    rec = await run_one(*job, args, http, session, gschemas, files)
                    rec["seed"] = args.seed
                    out.write(json.dumps(rec) + "\n"); out.flush()
                    print(f"{rec['task']} {rec['model']} {rec['condition']} {rec['grade']} retrieved={rec['retrieved_tokens']} "
                          f"turns={rec['turns']} {rec['seconds']}s" + (f" ERROR {rec['error']}" if rec["error"] else ""), flush=True)

            await asyncio.gather(*(go(j) for j in jobs))
            out.close()

        if any(CONDITIONS[c][1] for c in conds):
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
            async with streamablehttp_client(os.environ["MCP_URL"], headers={"Authorization": f"Bearer {os.environ['MCP_TOKEN']}"}) as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    await execute(session, graph_schemas((await session.list_tools()).tools))
        else:
            await execute(None, [])


if __name__ == "__main__":
    asyncio.run(main())
