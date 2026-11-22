"""Judge calibration (DESIGN.md section 9, step 6): hand-written good / partial / poor answers must get the
expected grade from the judge before the judge is used.

  python judge_calibrate.py ../tasks/fastapi-balanced.jsonl ../tasks/fastapi-judge-calibration.jsonl [judge-model]
"""
import asyncio, json, os, sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from run import grade, judge  # noqa: E402


async def main():
    tasks = {t["id"]: t for t in (json.loads(l) for l in Path(sys.argv[1]).read_text().splitlines() if l.strip())}
    cases = [json.loads(l) for l in Path(sys.argv[2]).read_text().splitlines() if l.strip()]
    model = sys.argv[3] if len(sys.argv) > 3 else "claude-sonnet-5.5"
    ok = 0
    async with httpx.AsyncClient(base_url=os.environ["CI_BASE_URL"],
                                 headers={"Authorization": f"Bearer {os.environ['CI_API_KEY']}"}, timeout=240) as http:
        for c in cases:
            t = tasks[c["task"]]
            cov, raw, _ = await judge(http, model, t, c["answer"])
            g, _, _ = grade(t, {"files": [], "symbols": []}, cov)
            ok += g == c["expect"]
            print(json.dumps({"task": c["task"], "expect": c["expect"], "got": g, "coverage": cov,
                              "covered": (raw or {}).get("covered")}))
    print(f"RESULT {ok}/{len(cases)} as expected")


asyncio.run(main())
