# Validation record: FastAPI balanced set (2026-11-14)

These are the steps in [DESIGN.md](DESIGN.md) section 9, run before the main run. They found four problems, and all four were fixed before any counted run.

| # | Step | Result | What it caught |
|---|---|---|---|
| 1 | Re-derive the structural keys (4.2, 4.3) with `keys/fastapi_callgraph.py` | ✅ all 12 match | – |
| 2 | Check that every lookup and name key exists at the commit | ✅ after one fix | **fb-23's key was wrong.** The duplicate-operation-ID warning is in `get_openapi_operation_metadata` (`fastapi/openapi/utils.py:279`, message at :291), not in `get_openapi` |
| 3 | Cite a `file:line` for every rubric point | ✅ after one rewrite | **fb-28's rubric described older FastAPI.** At this commit, `include_router` no longer copies routes: it appends an `_IncludedRouter` wrapper with an include context (`fastapi/routing.py:3373-3425`). The rubric was rewritten from the code |
| – | Design review | ✅ after one swap | **fb-22 overlapped fb-07** (both started at `get_route_handler`). It was replaced with `solve_dependencies → request_body_to_args → _extract_form_body` |
| 4 | Leak check: no ambiguous or unknown-name question contains its key symbol | ✅ pass | – |
| 5 | Grader self-test: the key graded as an answer is correct, an empty answer is wrong, half a key is partial | ✅ pass, 30/30 | – |
| 6 | Judge calibration | ✅ on the second round | see below |
| 7 | Dry run | ✅ after one fix | **C0 measured nothing.** With the shared prompt ("use the tools…") and no tools, models wrote fake tool calls as text and never answered. C0 now states that there are no tools (DESIGN.md section 3) |

## Step 6: judge calibration (`claude-sonnet-5.5`)

There were 18 hand-written answers: a good, a partial and a poor one for each of the 6 rubric questions ([tasks/fastapi-judge-calibration.jsonl](tasks/fastapi-judge-calibration.jsonl)).

- **Round 1: 13 of 18 got the expected grade.** All 12 good and poor answers were graded as expected, with every point matching. Five of the six "partial" answers came out wrong (four) or correct (one). Reading the judge's per-point verdicts, the main cause was the answers themselves: four of the partials covered only 2 of 5 points (0.4), which is below the 0.5 partial band. Across all 96 points, the judge agreed with the intended verdict on 92 (96%). Of the 4 disagreements, three were strict calls and one was lenient:
  - strict: it required "rebuilt when the routes change"
  - strict: it required the `jsonable_encoder` detail
  - strict: it required the explicit "does not copy" wording
  - lenient: "returns the token" was accepted without "does not validate"

  The round 1 answers are kept in [tasks/fastapi-judge-calibration-v1.jsonl](tasks/fastapi-judge-calibration-v1.jsonl).
- **Round 2: 18 of 18 as expected.** The five partial answers were rewritten to cover a clear 3 of 5 (or 3 of 6) points. Nothing about the judge was changed.

**Disclosed limitation:** the judge leans strict on qualifiers. That may slightly lower explanatory scores in every condition equally, since the judge is blind to the condition.

## Step 7: dry run

- **Main dry run:** fb-04 (set) and fb-11 (rubric) × C0–C3 × `claude-haiku-5.5`, 8 runs. All records were complete. Set grading (recall, precision, extras), the judge, "found" and C3's mixed tool use all worked.
- **The C0 fix was re-checked** on fb-04, fb-11 and fb-28 × 3 models, 9 runs. Models now answer from memory:
  - fb-11 (dependency resolution) was answered correctly from memory by all three models.
  - fb-28 was answered with the old "copies the routes" behaviour by all three, so it is wrong at this commit, as the memory trap intends.
  - One deepseek answer was empty. It is graded wrong and counted as an empty answer in the report.

The dry-run records are not part of the results.
