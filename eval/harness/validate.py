"""Offline validation of a question set (DESIGN.md section 9, steps 4 and 5). No model calls.

  python validate.py ../tasks/fastapi-balanced.jsonl
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run import grade  # noqa: E402

tasks = [json.loads(l) for l in Path(sys.argv[1]).read_text().splitlines() if l.strip()]
fail = 0
cats = {}
for t in tasks:
    cats[t["category"]] = cats.get(t["category"], 0) + 1
    # step 4: leak check for ambiguous / unknown-name questions
    if t["category"] == "ambiguous":
        for s in t["key"]["symbols"]:
            if s.lower() in t["question"].lower():
                print(f"LEAK {t['id']}: question contains key symbol {s}"); fail += 1
    if t["type"] == "rubric":
        g, _, _ = grade(t, {"files": [], "symbols": []}, 1.0); ok = g == "correct"
        g2, _, _ = grade(t, {"files": [], "symbols": []}, 0.6); ok &= g2 == "partial"
        g3, _, _ = grade(t, {"files": [], "symbols": []}, 0.2); ok &= g3 == "wrong"
    else:
        # step 5: the key as answer is correct; an empty answer is wrong; half the key is partial (where defined)
        key = t["key"]
        full = {"files": key.get("files", []), "symbols": key["symbols"]}
        g, _, _ = grade(t, full, None); ok = g == "correct"
        g2, _, _ = grade(t, {"files": [], "symbols": []}, None); ok &= g2 == "wrong"
        if t["type"] in ("set", "chain") and len(key["symbols"]) >= 2:
            half = {"files": [], "symbols": key["symbols"][: (len(key["symbols"]) + 1) // 2]}
            g3, _, _ = grade(t, half, None); ok &= g3 == "partial"
        if t["type"] == "lookup":
            g3, _, _ = grade(t, {"files": key["files"], "symbols": ["not_the_symbol"]}, None); ok &= g3 == "partial"
    if not ok:
        print(f"GRADER-SELFTEST FAIL {t['id']}"); fail += 1
print("categories:", cats, "total:", len(tasks))
print("RESULT", "PASS" if fail == 0 else f"FAIL ({fail})")
sys.exit(1 if fail else 0)
