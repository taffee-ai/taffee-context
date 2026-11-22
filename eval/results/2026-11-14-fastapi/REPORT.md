# Grep, graph, or both: FastAPI, 2026-11-14

**1,080 agent runs: 30 questions × 4 tool conditions × 3 models × 3 repeats. 0 errors. API cost $6.52.**

## Summary

- **The pre-registered "best of both" test failed for all three models.** Giving the agent graph tools alongside grep (C3) matched grep alone (C1) on accuracy: 0.90 against 0.90. But it used **54% more total tokens per correct answer**: 24.6k against 16.0k.
- **Grep alone was the most efficient condition overall.** Graph tools alone (C2) were the least efficient, at 35.6k tokens per correct answer, and slightly less accurate, at 0.86.
- **The graph helped in specific places:**
  - Questions where the name isn't known: C2 scored 1.00 against 0.95 for grep.
  - The one question about code that changed recently (fb-28): C2 scored 1.00 against 0.78 for grep.
  - Callers questions: C2 retrieved 42% less text. But it was also less accurate there, at 0.69 against 0.91.
- **Why "both" cost more:**
  - The graph tool definitions add about 1,430 tokens to every model call.
  - In C3, agents mostly used grep and file reads anyway. They called `query_graph` only 11 times in 270 runs.
- **The models already know FastAPI.** With no tools at all (C0), they scored 0.70 overall and **1.00 on lookups**. Lookup questions on a famous public repo measure memory, not retrieval.

So on this repo, with these questions and the shipped tool defaults, we can't claim that "both" is better, or that the graph reduces retrieved text. Section 6 lists what we will change and test next.

## 1. Test design

The full design is in [../../DESIGN.md](../../DESIGN.md), and the validation record is in [../../VALIDATION.md](../../VALIDATION.md). In brief:

| | |
|---|---|
| Repo | [fastapi/fastapi](https://github.com/fastapi/fastapi) at `913c68062c8990ea2c00d856d81b7e2383485155` (MIT). Graph: 9,342 nodes and 18,919 edges, plus 1,638 embedded chunks |
| Questions | 30, in five categories of 6: lookup, callers/impact, call chains, ambiguous or unknown names, explanatory ([tasks](../../tasks/fastapi-balanced.md)) |
| Keys | derived independently of the graph. Structural keys come from Python's `ast` ([keys/fastapi_callgraph.py](../../keys/fastapi_callgraph.py)), and every key cites `file:line` |
| Conditions | **C0** no tools · **C1** grep only (`grep`, `read_file`, `glob`) · **C2** graph only (11 MCP graph tools, including `read_code` and `semantic_search`; no MCP-Turbo pack) · **C3** both |
| Models (agents) | `claude-haiku-5.5`, `deepseek-v4.1-flash`, `claude-haiku-4.5`, at temperature 0.3 with a 14-turn cap |
| Judge | `claude-sonnet-5.5`, for the explanatory questions only. It is blind to condition and model, and was calibrated 18/18 before use |
| Repeats | 3 per question per condition per model, in random order (seed 20261114) |
| Tool enforcement | the harness implements every tool. There is no shell and no access outside the checkout |
| Retrieved tokens | all tool output returned to the agent, counted with `o200k_base` |
| Total tokens | the model's own usage counts, input plus output, over all turns |
| Hardware | MacBook Air, Intel i3-1000NG4 (2 cores / 4 threads), with a Docker Desktop VM of 4 CPUs and 8 GB. Neo4j 5.26.0, Graphify 0.9.51 (code-only), embedding cap 2,048 tokens |

Validation found and fixed four problems before the main run. Details are in [VALIDATION.md](../../VALIDATION.md).
- One wrong key.
- One rubric that described an older FastAPI.
- One overlapping question.
- A C0 prompt under which models wrote fake tool calls instead of answering.

## 2. Pre-registered predictions against outcomes

| Category | Prediction | Outcome | |
|---|---|---|---|
| Lookup | C3 retrieved within ±10% of C1; accuracy equal | C3 +267% (367 against 100 tokens, both tiny); all conditions, including C0, scored 1.00 | ❌ / ✅ |
| Callers | C3 retrieves less than C1; C3 accuracy ≥ C1 | −15%; 0.87 against 0.91 | ✅ / ❌ |
| Chain | C3 retrieves less than C1; C3 accuracy ≥ C1 | +2%; 0.69 against 0.69 | ❌ / ✅ (tie) |
| Ambiguous | C3 retrieves ≤ C1; C3 accuracy > C1 | +24%; 0.98 against 0.95 | ❌ / ✅ |
| Explanatory | retrieval uncertain; C3 accuracy > C1 | +3%; 0.96 against 0.94 | – / ✅ (small) |
| Overall | C3 has the lowest tokens per correct answer of C1–C3 | C1 16.0k, C3 24.6k, C2 35.6k | ❌ |
| **Best of both** | C3 ≥ the better of C1 and C2 in every category, **and** the lowest tokens per correct | fails for all 3 models (table 3.2) | **❌** |

## 3. Results

### 3.1 All models pooled

Score is the mean grade (1 / 0.5 / 0). Token columns are medians of per-question medians.

| Category | Condition | Score | Retrieved tokens | Total tokens | Tokens per correct | Turns |
|---|---|---|---|---|---|---|
| lookup | C0 none | 1.00 | 0 | 290 | 335 | 0 |
| | C1 grep | 1.00 | 100 | 1,877 | 2,683 | 1 |
| | C2 graph | 1.00 | 877 | 7,886 | 8,287 | 1 |
| | C3 both | 1.00 | 367 | 6,323 | 6,790 | 1 |
| callers | C0 none | 0.39 | 0 | 799 | 2,402 | 0 |
| | C1 grep | **0.91** | 2,254 | 12,314 | **14,661** | 3 |
| | C2 graph | 0.69 | **1,311** | 13,202 | 34,409 | 2 |
| | C3 both | 0.87 | 1,922 | 14,916 | 19,447 | 2 |
| chain | C0 none | 0.59 | 0 | 1,304 | 2,090 | 0 |
| | C1 grep | 0.69 | 3,793 | 12,460 | **26,955** | 3 |
| | C2 graph | 0.68 | **2,984** | 20,816 | 47,368 | 3 |
| | C3 both | 0.69 | 3,875 | 20,562 | 40,989 | 3 |
| ambiguous | C0 none | 0.83 | 0 | 488 | 747 | 0 |
| | C1 grep | 0.95 | **1,102** | 5,733 | **8,989** | 2 |
| | C2 graph | **1.00** | 3,234 | 20,917 | 28,970 | 3 |
| | C3 both | 0.98 | 1,371 | 13,014 | 15,754 | 2 |
| explanatory | C0 none | 0.68 | 0 | 1,234 | 1,962 | 0 |
| | C1 grep | 0.94 | **3,908** | 21,653 | **30,765** | 4 |
| | C2 graph | 0.95 | 6,855 | 33,417 | 63,596 | 4 |
| | C3 both | **0.96** | 4,014 | 29,770 | 45,292 | 3 |
| **all** | C0 none | 0.70 | 0 | 722 | 1,277 | 0 |
| | C1 grep | **0.90** | **1,610** | **10,498** | **16,044** | 2 |
| | C2 graph | 0.86 | 2,713 | 18,516 | 35,573 | 3 |
| | C3 both | **0.90** | 2,011 | 17,188 | 24,640 | 2 |

### 3.2 The "best of both" test, per model

| Model | lookup | callers | chain | ambiguous | explanatory | Tokens per correct (C1 / C2 / C3) | Result |
|---|---|---|---|---|---|---|---|
| claude-haiku-4.5 | ✅ 1.00 vs 1.00 | ❌ 0.81 vs 0.89 | ❌ 0.69 vs 0.72 | ✅ 1.00 vs 1.00 | ✅ 0.94 vs 0.89 | 14,646 / 28,806 / 23,569 ❌ | **FAIL** |
| claude-haiku-5.5 | ✅ 1.00 vs 1.00 | ❌ 0.89 vs 0.92 | ✅ 0.78 vs 0.75 | ✅ 1.00 vs 1.00 | ❌ 0.94 vs 0.97 | 14,878 / 34,458 / 19,839 ❌ | **FAIL** |
| deepseek-v4.1-flash | ✅ 1.00 vs 1.00 | ✅ 0.92 vs 0.92 | ❌ 0.58 vs 0.61 | ❌ 0.94 vs 1.00 | ✅ 1.00 vs 1.00 | 18,668 / 43,470 / 30,691 ❌ | **FAIL** |

Each cell compares C3's score with the better of C1 and C2.

Per-model tables, per-question results and reliability counts are in [tables.md](tables.md).

### 3.3 What the tools returned

| Condition | Most-used tools (calls, tokens per call) |
|---|---|
| C1 grep | `read_file` (699, 699 per call) · `grep` (592, 377) · `glob` (39, 101) |
| C2 graph | `read_code` (669, 851) · `semantic_search` (350, 428) · `get_neighbors` (181, 265) · `query_graph` (177, 1,628) · `get_node` (69, 111) |
| C3 both | `grep` (516, 315) · `read_code` (479, 787) · `read_file` (175, 699) · `semantic_search` (80, 471) · `query_graph` (11, 986) |

**Tool definitions sent with every model call:** file tools come to 245 tokens and graph tools to 1,434. C3 sends both, 1,678 tokens.

## 4. Analysis

**1. Grep alone was the strongest baseline.** In C1, agents grepped for a likely name and then read a line range. That is cheap and usually enough. It had the best tokens per correct answer of C1–C3 in every category (pooled), and overall for each of the three models.

**2. "Both" mostly behaved like grep plus a pricier read.** In C3, agents chose `grep` (516 calls) and `read_code` (479 calls, 787 tokens per call against 699 for `read_file`). The structural graph tools were rarely used: `query_graph` 11 times, `shortest_path` 14, `affected` 2. So C3 paid for the graph tools without using them:
- the graph tool definitions, about 1,430 extra tokens on every model call
- slightly heavier reads

That is why C3's retrieved text was close to C1's while its total tokens were much higher.

**3. Graph-only retrieved less on structural questions, but lost accuracy on callers.** On callers questions C2 retrieved 42% less than C1, but scored 0.69 against 0.91. The largest loss was fb-04, at 0.28 against 1.00: `solve_dependencies` is called from inside nested functions (`get_request_handler.app`, `get_websocket_app.app`), and the code-only graph's name-matched call edges didn't lead agents to those callers. This points at graph construction (edges from nested functions), not at the agents.

**4. The graph helped where the name or the code is unfamiliar:**
- **Ambiguous or unknown names:** C2 scored 1.00 against 0.95 for C1. On fb-25 (where path parameter names are extracted) it scored 1.00 against 0.78.
- **Code that changed recently (fb-28):** at this commit, `include_router` no longer copies routes. All models answered from memory with the old behaviour, so C0 scored 0.00. Grep scored 0.78 and graph 1.00.

Both effects are small, measured on a few questions.

**5. Memory confounds benchmarks on public repos.** C0 scored 0.70 overall without reading any code, and 1.00 on lookups. On FastAPI, lookups therefore measure only tool cost, not search ability. Any retrieval claim should be tested on code the models can't have memorised: newer, private or changed code.

**6. Sensitivity: the chain keys were too narrow.** On fb-07, fb-21 and fb-22, agents found every key function in 77 of 81 runs. They also named other functions that really are on the path (for example, `solve_dependencies` runs before the endpoint in fb-07). The pre-registered grader allows at most one extra name, so those answers scored partial in every condition. Scoring sets and chains on recall alone doesn't change any conclusion:

| Rescored (recall only) | C1 grep | C2 graph | C3 both |
|---|---|---|---|
| Score, all categories | 0.96 | 0.92 | 0.97 |
| Tokens per correct answer | 14,935 | 33,359 | 22,897 |

The pre-registered grading remains the official result.

## 5. Limitations

- **One repo,** and a famous one, so memory is strong (see point 5 above). Results may differ on unfamiliar or private code.
- **The questions are ours.** The keys are independent of the graph, but we chose the questions. A question set derived from pull requests is planned.
- **The C1 baseline is lean** (line-level grep, ranged reads), which favours grep. A "typical defaults" baseline is planned.
- **The graph is code-only** (tree-sitter, with call edges matched by name), and the graph tools use their shipped defaults (for example, `token_budget=2000`).
- **The judge leans strict on qualifiers** ([VALIDATION.md](../../VALIDATION.md)). It is blind to the condition, so the effect applies equally to all conditions.
- **Small samples:** 9 runs per question per condition. Differences of a few hundredths in score are within noise.
- **One provider, one date.** Model routing may change over time.

## 6. What we will change and test next

1. **Cut the graph's fixed cost.** Offer a small graph tool set in the "both" condition, with fewer and shorter definitions, and slim the output of `read_code` and `query_graph`.
2. **Fix caller edges from nested functions** in graph construction (the fb-04 failure).
3. **Test on code the models don't know:** newer or less famous repos, and private-style code, where memory doesn't help and grep's noise grows with size.
4. **Repeat on nestjs** with a balanced set whose keys come from the TypeScript compiler.
5. **Add the "typical defaults" baseline**, so the result can be compared against how off-the-shelf agents search.

## 7. Reproduce

```sh
# 1. Fetch fastapi at the pinned commit (eval/repos.yaml) and ingest it (graph + embeddings), see docs/guides/
# 2. Start the stack (Neo4j + MCP server) from taffee-core/infra/compose.yaml
# 3. Validate, calibrate, run, report:
python eval/harness/validate.py eval/tasks/fastapi-balanced.jsonl
python eval/harness/judge_calibrate.py eval/tasks/fastapi-balanced.jsonl eval/tasks/fastapi-judge-calibration.jsonl
docker build -f eval/Dockerfile -t taffee-eval:dev .
docker run --rm -e CI_BASE_URL -e CI_API_KEY -e MCP_URL -e MCP_TOKEN -v <checkouts>:/repos:ro -v $PWD/eval/tasks:/tasks:ro \
  -v $PWD/out:/results taffee-eval:dev --tasks /tasks/fastapi-balanced.jsonl --repo fastapi \
  --commit 913c68062c8990ea2c00d856d81b7e2383485155 --checkout /repos/fastapi \
  --models claude-haiku-5.5,deepseek-v4.1-flash,claude-haiku-4.5 --conditions C0,C1,C2,C3 --runs 3 --workers 6 --out /results/runs.jsonl
python eval/harness/report.py out/runs.jsonl
```

Any OpenAI-compatible endpoint works. Set `CI_BASE_URL` and `CI_API_KEY`.

**Data:** [runs.jsonl](runs.jsonl) holds all 1,080 runs, with every tool call, its token count, the model's usage counts, the answer, the grade and the judge verdicts. [tables.md](tables.md) has every table generated from it.

## Earlier pilots

These are not part of this result, and are listed for transparency.
- **FastAPI, 10 lookup questions, 2 conditions (graph only against grep only):** graph tools retrieved 43% and 177% more text, depending on the model, with 100% accuracy in both conditions.
- **nestjs, a re-run of the October pilot's 5 questions under this harness:** graph tools retrieved 7–13× more than grep. The October −34% result came from a baseline whose agents read whole files through a shell.

## Acknowledgement

Model inference for the agent runs and the judge was provided by Cheaperinference.
