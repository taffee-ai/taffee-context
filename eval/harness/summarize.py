"""Summarise run JSONL: per model, file search (A) against graph tools (B). Usage: python summarize.py run.jsonl"""
import json, statistics as st, sys
from collections import defaultdict

rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
by = defaultdict(list)
for r in rows:
    by[(r["model"], r["condition"])].append(r)

def med(xs):
    return st.median(xs) if xs else 0

print(f"{'model':24} {'cond':4} {'runs':>4} {'retrieved med':>13} {'retrieved sum':>13} {'signal':>6} {'found':>6} "
      f"{'correct':>7} {'partial':>7} {'wrong':>5} {'err':>3} {'found-but-wrong':>15} {'ctx med':>8} {'turns':>5} {'sec med':>7}")
for model in sorted({m for m, _ in by}):
    res = {}
    for cond in ("A", "B"):
        rs = by.get((model, cond), [])
        if not rs:
            continue
        ok = [r for r in rs if r["grade"] != "error"]
        g = lambda k: sum(r["grade"] == k for r in rs)
        res[cond] = med([r["retrieved_tokens"] for r in ok])
        print(f"{model:24} {cond:4} {len(rs):4} {res[cond]:13.0f} {sum(r['retrieved_tokens'] for r in ok):13} "
              f"{med([r['signal_ratio'] for r in ok]):6.2f} {sum(r['found'] for r in ok):6} {g('correct'):7} {g('partial'):7} "
              f"{g('wrong'):5} {g('error'):3} {sum(r['found'] and r['grade'] != 'correct' for r in ok):15} "
              f"{med([r['usage']['prompt_tokens'] for r in ok]):8.0f} {med([r['turns'] for r in ok]):5.0f} {med([r['seconds'] for r in ok]):7.1f}")
    if "A" in res and "B" in res and res["A"]:
        print(f"{'':24} B vs A median retrieved: {100 * (res['B'] - res['A']) / res['A']:+.1f}%")
    # per-task medians, so one outlier task can't drive the headline
    pt = []
    for t in sorted({r["task"] for r in rows if r["model"] == model}):
        a = [r["retrieved_tokens"] for r in by.get((model, "A"), []) if r["task"] == t and r["grade"] != "error"]
        b = [r["retrieved_tokens"] for r in by.get((model, "B"), []) if r["task"] == t and r["grade"] != "error"]
        if a and b and med(a):
            pt.append(100 * (med(b) - med(a)) / med(a))
    if pt:
        print(f"{'':24} per-task change, median over tasks: {med(pt):+.1f}% (tasks: {len(pt)})")
