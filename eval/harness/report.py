"""Build the results tables (markdown) from a run JSONL. See eval/DESIGN.md section 6.

  python report.py results.jsonl > results.md

Summaries use the median of per-question medians (retrieval, tokens) and the mean score, so no single
question drives a headline. Prices are list prices per million tokens on the run date (cached input is
priced at the cached rate when the provider reports it).
"""
import json, statistics as st, sys
from collections import defaultdict

PRICES = {  # USD per million: input, output, cached input (Cheaperinference list prices, 2026-11-14)
    "claude-haiku-5.5": (0.065, 0.325, 0.0065),
    "deepseek-v4.1-flash": (0.0145, 0.33, 0.00165),
    "claude-haiku-4.5": (0.65, 3.25, 0.065),
    "claude-sonnet-5.5": (1.473878, 7.36939, 0.0736939),
}
JUDGE_MODEL = "claude-sonnet-5.5"
CATS = ["lookup", "callers", "chain", "ambiguous", "explanatory"]
CONDS = ["C0", "C1", "C2", "C3"]
COND_NAME = {"C0": "C0 none", "C1": "C1 grep", "C2": "C2 graph", "C3": "C3 both"}

rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
models = sorted({r["model"] for r in rows})


def cost(model, u):
    i, o, c = PRICES[model]
    cached = u.get("cached_tokens", 0) or 0
    return ((u.get("prompt_tokens", 0) - cached) * i + cached * c + u.get("completion_tokens", 0) * o) / 1e6


for r in rows:
    r["total_tokens"] = r["usage"]["prompt_tokens"] + r["usage"]["completion_tokens"]
    r["cost"] = cost(r["model"], r["usage"])
    r["judge_cost"] = cost(JUDGE_MODEL, r["judge_usage"]) if r.get("judge_usage") else 0.0


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def mom(rs, f):
    """Median over questions of the per-question median of f."""
    byq = defaultdict(list)
    for r in rs:
        byq[r["task"]].append(f(r))
    return med([med(v) for v in byq.values()])


def fmt(x, d=0):
    return "–" if x is None else f"{x:,.{d}f}"


def summary(rs):
    ok = [r for r in rs if r["grade"] != "error"]
    score = st.mean([r["score"] for r in rs]) if rs else None
    tot = sum(r["total_tokens"] for r in ok)
    pts = sum(r["score"] for r in ok)
    fnd = [r["found"] for r in ok if r["found"] is not None]
    return {
        "n": len(rs), "score": score,
        "retrieved": mom(ok, lambda r: r["retrieved_tokens"]),
        "total": mom(ok, lambda r: r["total_tokens"]),
        "tpc": (tot / pts) if pts else None,
        "found": (sum(fnd) / len(fnd)) if fnd else None,
        "turns": mom(ok, lambda r: r["turns"]),
        "sec": mom(ok, lambda r: r["seconds"]),
        "cost": sum(r["cost"] for r in rs),
        "errors": sum(r["grade"] == "error" for r in rs),
        "capped": sum(bool(r.get("capped")) for r in rs),
        "empty": sum(not (r.get("final_text") or "").strip() for r in rs),
        "fbw": sum(bool(r["found"]) and r["grade"] != "correct" for r in ok),
        "cbnf": sum(r["found"] is False and r["grade"] == "correct" for r in ok),
    }


def table(group_rows, title):
    print(f"\n### {title}\n")
    print("| Category | Condition | Runs | Score | Retrieved tokens (med) | Total tokens (med) | Tokens per correct | Found | Turns (med) | Seconds (med) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for cat in CATS + ["all"]:
        for c in CONDS:
            rs = [r for r in group_rows if r["condition"] == c and (cat == "all" or r["category"] == cat)]
            if not rs:
                continue
            s = summary(rs)
            label = f"**{cat}**" if cat == "all" else cat
            print(f"| {label} | {COND_NAME[c]} | {s['n']} | {fmt(s['score'], 2)} | {fmt(s['retrieved'])} | {fmt(s['total'])} | "
                  f"{fmt(s['tpc'])} | {fmt(None if s['found'] is None else 100 * s['found'])}{'' if s['found'] is None else '%'} | "
                  f"{fmt(s['turns'])} | {fmt(s['sec'], 1)} |")


def deltas(group_rows, title):
    print(f"\n### {title}\n")
    print("| Category | C3 vs C1 retrieved | C3 vs C1 score | C2 vs C1 retrieved | C2 vs C1 score | C0 score (memory) |")
    print("|---|---|---|---|---|---|")
    for cat in CATS + ["all"]:
        s = {c: summary([r for r in group_rows if r["condition"] == c and (cat == "all" or r["category"] == cat)]) for c in CONDS}
        def pct(a, b):
            return "–" if a is None or b in (None, 0) else f"{100 * (a - b) / b:+.0f}%"
        def diff(a, b):
            return "–" if a is None or b is None else f"{a - b:+.2f}"
        label = f"**{cat}**" if cat == "all" else cat
        print(f"| {label} | {pct(s['C3']['retrieved'], s['C1']['retrieved'])} | {diff(s['C3']['score'], s['C1']['score'])} | "
              f"{pct(s['C2']['retrieved'], s['C1']['retrieved'])} | {diff(s['C2']['score'], s['C1']['score'])} | {fmt(s['C0']['score'], 2)} |")


def best_of_both(group_rows, model):
    by = lambda c, cat=None: summary([r for r in group_rows if r["condition"] == c and (cat is None or r["category"] == cat)])
    cat_ok = []
    for cat in CATS:
        c1, c2, c3 = by("C1", cat)["score"], by("C2", cat)["score"], by("C3", cat)["score"]
        if None in (c1, c2, c3):
            continue
        cat_ok.append((cat, c3 >= max(c1, c2) - 1e-9, c1, c2, c3))
    t1, t2, t3 = by("C1")["tpc"], by("C2")["tpc"], by("C3")["tpc"]
    tpc_ok = t3 is not None and all(t3 <= x for x in (t1, t2) if x is not None)
    return cat_ok, tpc_ok, (t1, t2, t3)


print("## Results\n")
print(f"Runs: {len(rows)}. Errors: {sum(r['grade'] == 'error' for r in rows)}. "
      f"Agent cost: ${sum(r['cost'] for r in rows):.2f}. Judge cost: ${sum(r['judge_cost'] for r in rows):.2f}.")

table(rows, "All models pooled")
deltas(rows, "Differences, all models pooled (median-of-medians for tokens, mean for score)")

print("\n### Pre-registered \"best of both\" test, per model\n")
print("Passes only if C3's score ≥ the better of C1 and C2 in **every** category, **and** C3 has the lowest tokens per correct answer of C1–C3.\n")
print("| Model | lookup | callers | chain | ambiguous | explanatory | Tokens per correct (C1 / C2 / C3) | Result |")
print("|---|---|---|---|---|---|---|---|")
for m in models:
    cat_ok, tpc_ok, (t1, t2, t3) = best_of_both([r for r in rows if r["model"] == m], m)
    cells = [("✅" if ok else "❌") + f" {c3:.2f} vs {max(c1, c2):.2f}" for _, ok, c1, c2, c3 in cat_ok]
    passed = all(ok for _, ok, *_ in cat_ok) and tpc_ok
    print(f"| {m} | " + " | ".join(cells) + f" | {fmt(t1)} / {fmt(t2)} / {fmt(t3)} {'✅' if tpc_ok else '❌'} | **{'PASS' if passed else 'FAIL'}** |")

for m in models:
    table([r for r in rows if r["model"] == m], f"Per model: {m}")

print("\n### Retrieved tokens by tool (all models)\n")
print("| Condition | Tool | Calls | Tokens | Tokens per call |")
print("|---|---|---|---|---|")
agg = defaultdict(lambda: [0, 0])
for r in rows:
    for c in r["calls"]:
        agg[(r["condition"], c["tool"])][0] += 1
        agg[(r["condition"], c["tool"])][1] += c["result_tokens"]
for (cond, tool), (n, t) in sorted(agg.items(), key=lambda x: (x[0][0], -x[1][1])):
    print(f"| {COND_NAME[cond]} | `{tool}` | {n:,} | {t:,} | {t // n:,} |")

print("\n### Reliability and diagnostics\n")
print("| Condition | Errors | Empty answers | Turn-cap hits | Found but not correct | Correct but key not retrieved | Agent cost (USD) |")
print("|---|---|---|---|---|---|---|")
for c in CONDS:
    s = summary([r for r in rows if r["condition"] == c])
    print(f"| {COND_NAME[c]} | {s['errors']} | {s['empty']} | {s['capped']} | {s['fbw']} | {s['cbnf']} | {s['cost']:.2f} |")

print("\n### Per question (all models; score mean / retrieved median)\n")
print("| Question | Category | C0 | C1 | C2 | C3 |")
print("|---|---|---|---|---|---|")
for q in sorted({r["task"] for r in rows}, key=lambda x: (CATS.index(next(r["category"] for r in rows if r["task"] == x)), x)):
    cat = next(r["category"] for r in rows if r["task"] == q)
    cells = []
    for c in CONDS:
        rs = [r for r in rows if r["task"] == q and r["condition"] == c]
        cells.append(f"{st.mean([r['score'] for r in rs]):.2f} / {fmt(med([r['retrieved_tokens'] for r in rs]))}" if rs else "–")
    print(f"| {q} | {cat} | " + " | ".join(cells) + " |")
