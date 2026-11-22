# Evaluation design: grep, graph, or both

Status: **validated and run on 2026-11-14.** Validation found four problems and they were fixed before the main run (see [VALIDATION.md](VALIDATION.md)). The changes are marked *(changed in validation)* below. Results: [results/2026-11-14-fastapi/REPORT.md](results/2026-11-14-fastapi/REPORT.md).

## 1. Question

Does giving a coding agent the Context pillar's graph tools, alongside or instead of plain text search, change:

1. how much code text it has to retrieve,
2. how often it answers correctly, and
3. what the answer costs in total?

The comparison is always between conditions **on the same model**. Comparing models is not a goal.

## 2. What runs

One **run** is one model answering one question under one condition:

1. The harness sends the question and a fixed system prompt to the model, along with the condition's tools (or none).
2. The model calls tools. The harness executes each call itself and returns the result. The model has no other access: no shell, no other paths.
3. The loop ends when the model gives a final answer, or at 14 tool turns. At the cap, the model is asked for its final answer with tools removed.
4. The harness records every tool call, the tokens each returned, the model's own usage counts, the timing and the final answer, then grades it.

| | Value |
|---|---|
| Repo | fastapi/fastapi at `913c68062c8990ea2c00d856d81b7e2383485155`. nestjs follows with its own set (section 11) |
| Questions | 30, in 5 categories of 6 (section 4) |
| Conditions | 4 (section 3) |
| Models (agents) | `claude-haiku-5.5`, `deepseek-v4.1-flash`, `claude-haiku-4.5` (via Cheaperinference) |
| Runs per question per condition per model | 3 |
| Total agent runs | 30 × 4 × 3 × 3 = **1,080** |
| Judge model (explanatory questions only) | `claude-sonnet-5.5`, which is not one of the agents |
| Judge calls | 6 questions × 4 × 3 × 3 = **216** |
| Estimated API cost | about $5–8 in total |
| Where | One laptop (Intel Core i3-1000NG4, 2 cores / 4 threads, 16 GB RAM), all in Docker: Neo4j, the MCP server and the harness container |

## 3. Conditions

All four conditions use the same system prompt, model settings, turn cap and answer format. Only the tool list differs.

| # | Condition | Tools the agent gets |
|---|---|---|
| C0 | **No grep, no graph** | none. The model answers from what it already knows |
| C1 | **Grep only** | `grep` (regex search, returns `path:line: text`, max 100 matches), `read_file` (line ranges, max 2,000 lines per call), `glob` (file paths, max 200) |
| C2 | **Graph only** | the MCP server's read-only tools: `semantic_search`, `query_graph`, `get_node`, `explain`, `get_neighbors`, `affected`, `god_nodes`, `get_community`, `shortest_path`, `graph_stats`, `read_code`. `assemble_context_pack` (MCP-Turbo) is excluded |
| C3 | **Both** | C1 + C2 |

Notes:
- **C2 can still read source.** `read_code` returns committed source lines. What C2 lacks is text search.
- **C1 is a lean baseline.** Its `grep` returns matching lines and `read_file` takes line ranges, so a careful agent can answer lookups cheaply. This is a stated design choice. A "typical defaults" baseline (file-name-only grep, whole-file reads) can be added as a later variant.
- **Graph tools use their shipped defaults**, for example `token_budget=2000`. Results are reported against those defaults.

System prompt (identical across conditions; `{repo}` = `fastapi`):

> You answer questions about the source code of the repository '{repo}' at a fixed commit. Use the tools to find the answer in the code; do not guess without checking. Be efficient. When you are confident, reply with a short answer that ends with one JSON object on its own line: {"files": [...], "symbols": [...]}

*(Changed in validation.)* In C0, the sentence "Use the tools to find the answer in the code; do not guess without checking." is replaced by "You have no tools: answer from what you already know about this repository." In the dry run, the unmodified prompt led models to write fake tool calls as text instead of answering, so C0 measured nothing. The rest of the prompt is identical in all four conditions. Explanatory answers are free text, followed by the same JSON line.

## 4. Questions

There are 30 questions in 5 categories of 6. The keys are derived **independently of the graph under test**:
- **Structural keys** (callers, chains) come from [keys/fastapi_callgraph.py](keys/fastapi_callgraph.py), which uses Python's own parser (`ast`).
- **Lookup and name keys** are checked against the code with grep.
- **Rubric points** each cite the code they come from, as `file:line`.

Column **V**: ✅ means validated (section 9). All 30 keys are validated, with a citation for each in [tasks/fastapi-balanced.jsonl](tasks/fastapi-balanced.jsonl) (the `cite` field).

### 4.1 Lookup: a known name, find where it is (grep's home ground)

| ID | Question | Key | V |
|---|---|---|---|
| fb-01 | Which class represents a file uploaded in a request? | `fastapi/datastructures.py` · `UploadFile` | ✅ |
| fb-02 | Which function renders the HTML page for the interactive Swagger UI docs? | `fastapi/openapi/docs.py` · `get_swagger_ui_html` | ✅ |
| fb-03 | What is the default exception handler for HTTPException? | `fastapi/exception_handlers.py` · `http_exception_handler` | ✅ |
| fb-13 | Which function renders the ReDoc documentation page? | `fastapi/openapi/docs.py` · `get_redoc_html` | ✅ |
| fb-14 | Which class reads an API key from a request header? | `fastapi/security/api_key.py` · `APIKeyHeader` | ✅ |
| fb-15 | Which class implements HTTP Basic authentication? | `fastapi/security/http.py` · `HTTPBasic` | ✅ |

### 4.2 Callers and impact: who calls X, or what breaks if X changes

| ID | Question | Key (enclosing function of each call site) | V |
|---|---|---|---|
| fb-04 | Which functions or methods in the fastapi package call solve_dependencies directly? | `solve_dependencies` (recursive), `_FrontendRouteGroup._solve_dependencies`, `get_request_handler`, `get_websocket_app` | ✅ |
| fb-06 | If get_dependant's signature changed, which functions call it directly and would need updating? | `get_dependant` (recursive), `get_parameterless_sub_dependant`, `solve_dependencies`, `_build_dependant_with_parameterless_dependencies` | ✅ |
| fb-10 | Which of FastAPI's built-in exception handlers pass validation errors through jsonable_encoder? | `request_validation_exception_handler`, `websocket_request_validation_exception_handler` | ✅ |
| fb-16 | Which security classes split the Authorization header using get_authorization_scheme_param? | `HTTPBase`, `HTTPBasic`, `HTTPBearer`, `HTTPDigest`, `OAuth2AuthorizationCodeBearer`, `OAuth2PasswordBearer` | ✅ |
| fb-17 | Which functions call create_model_field? | `_get_body_field`, `analyze_param`, `_populate_api_route_state` | ✅ |
| fb-18 | Which methods register a WebSocket route by calling add_api_websocket_route? | `FastAPI.add_api_websocket_route`, `FastAPI.websocket`, `APIRouter.websocket` | ✅ |

### 4.3 Call chains: trace a path through several functions

| ID | Question | Key (in order) | V |
|---|---|---|---|
| fb-05 | Trace the call chain from FastAPI.openapi() down to the function that builds one operation's metadata (summary, description, operationId). | `openapi` → `get_openapi` → `get_openapi_path` → `get_openapi_operation_metadata` | ✅ |
| fb-07 | Starting at APIRoute.get_route_handler, which functions does a request pass through before the endpoint function is called? | `get_route_handler` → `get_request_handler` → `run_endpoint_function` | ✅ |
| fb-19 | Starting at FastAPI.setup, through which functions is the Swagger UI page produced? | `setup` → `swagger_ui_html` → `get_swagger_ui_html` | ✅ |
| fb-20 | Starting at get_dependant, through which functions does one endpoint parameter pass before a model field is created for it? | `get_dependant` → `analyze_param` → `create_model_field` | ✅ |
| fb-21 | Starting at get_openapi, through which functions does FastAPI go to build the parameters list of one operation? | `get_openapi` → `get_openapi_path` → `_get_openapi_operation_parameters` | ✅ |
| fb-22 | *(Changed in validation: the draft overlapped fb-07.)* Starting at solve_dependencies, through which functions do form fields pass before they are extracted from the request body? | `solve_dependencies` → `request_body_to_args` → `_extract_form_body` | ✅ |

### 4.4 Ambiguous or unknown names: the question doesn't give away the name

| ID | Question | Key | V |
|---|---|---|---|
| fb-08 | FastAPI has several functions whose names start with get_openapi. Which one builds the metadata (summary, description, operationId, tags) for a single operation? | `fastapi/openapi/utils.py` · `get_openapi_operation_metadata` | ✅ |
| fb-09 | Where are form fields (multipart or URL-encoded) pulled out of the request body and matched to the endpoint's parameters? | `fastapi/dependencies/utils.py` · `_extract_form_body` | ✅ |
| fb-23 | Where does FastAPI detect duplicate operation IDs and warn about them? | *(Changed in validation: the draft key, `get_openapi`, was wrong.)* `fastapi/openapi/utils.py` · `get_openapi_operation_metadata` | ✅ |
| fb-24 | Where are the routes for the interactive docs and the OpenAPI JSON added to the application? | `fastapi/applications.py` · `setup` | ✅ |
| fb-25 | Where are the parameter names extracted from a path template such as `/items/{item_id}`? | `fastapi/utils.py` · `get_path_param_names` | ✅ |
| fb-26 | Where is a dependency written as a plain (non-async) function run in a worker thread? | `fastapi/dependencies/utils.py` · `solve_dependencies` | ✅ |

### 4.5 Explanatory: open-ended, graded against a rubric

| ID | Question | Rubric points | V |
|---|---|---|---|
| fb-11 | Explain how FastAPI resolves a dependency that itself has sub-dependencies, including what happens when the same dependency is used twice in one request. | 1. `get_dependant` builds a dependency tree from signatures before requests arrive. 2. `solve_dependencies` resolves it recursively, sub-dependencies first. 3. Results are cached per request, so a repeated dependency runs once. 4. `use_cache=False` opts out. 5. `dependency_overrides` can replace a dependency | ✅ |
| fb-12 | Explain what happens from the moment a request reaches a path operation until the response is sent. | 1. `get_route_handler` uses `get_request_handler` to build the handler. 2. The body is read and parsed (JSON or form). 3. `solve_dependencies` validates parameters and runs dependencies, and errors raise `RequestValidationError` (422). 4. `run_endpoint_function` calls the endpoint, sync ones in a threadpool. 5. `serialize_response` validates and serializes against the response model. 6. The response class builds the response, with background tasks attached | ✅ |
| fb-27 | Explain how FastAPI produces the OpenAPI schema for an application. | 1. `FastAPI.openapi()` builds it once, caches it in `openapi_schema` and rebuilds it when the routes change. 2. It calls `get_openapi` with the app's routes. 3. `get_openapi` walks the routes and calls `get_openapi_path` for each. 4. Parameters, request bodies and responses become schema entries, with shared models in components. 5. Security schemes are collected from the security dependencies. 6. It is served at `openapi_url` by a route added in `setup` | ✅ |
| fb-28 | Explain what APIRouter.include_router does when you include a router with a prefix. *(Changed in validation: the draft rubric described older FastAPI, which copied routes. This commit doesn't, so the question is now also a memory trap.)* | 1. It refuses to include a router into itself, or into a router that already contains it. 2. It validates the prefix: it must start with `/` and not end with `/`. 3. It does **not** copy routes. It builds an include context: prefix, tags, dependencies, responses, callbacks, the unique-ID function. 4. It appends one `_IncludedRouter` that wraps the original router with that context, and routes resolve through it when requests are matched. 5. It carries over startup and shutdown handlers and merges the lifespan context | ✅ |
| fb-29 | Explain how a request validation error becomes an HTTP response. | 1. Errors are collected while solving dependencies and parsing the body. 2. `get_request_handler` raises `RequestValidationError`. 3. The app's default handler is `request_validation_exception_handler`. 4. It returns 422 with the errors encoded by `jsonable_encoder`. 5. The handler can be overridden through `exception_handlers` | ✅ |
| fb-30 | Explain how OAuth2PasswordBearer obtains the token, and what it does when the token is missing. | 1. `__call__` reads the Authorization header. 2. `get_authorization_scheme_param` splits the scheme and the value. 3. It checks that the scheme is bearer (case-insensitively). 4. If the header is missing or wrong and `auto_error` is set, it raises a 401 with `WWW-Authenticate: Bearer`, and otherwise returns None. 5. It returns the token string and does not validate the token itself | ✅ |

## 5. Grading

| Type | Used by | Correct (1) | Partial (0.5) | Wrong (0) |
|---|---|---|---|---|
| lookup | 4.1, 4.4 | names the key file and the key symbol | right file, wrong or missing symbol | wrong file |
| set | 4.2 | names every key symbol, with at most one extra | names at least half the key symbols | names fewer than half |
| chain | 4.3 | names every function in the chain | names at least half | names fewer than half |
| rubric | 4.5 | the judge marks at least 80% of points as covered | at least 50% | less than 50% |

- **Symbol matching:** exact name. A dotted name matches on any segment, so `get_request_handler.app` counts for `get_request_handler`. Paths match on the repo-relative suffix.
- **Chains:** graded as sets, so order isn't required. The order of each answer is recorded and reported separately.
- **The judge** receives only the question, the rubric points and the answer text. It never sees the condition, the model or the tool calls. It returns a covered/not-covered verdict per point, with a one-line reason.

## 6. Metrics

Every metric is recorded per run, reported per **condition × category × model**, and summarised as the median of per-question medians, so that no single question drives a headline.

### 6.1 Retrieval
| Metric | Definition |
|---|---|
| **Retrieved tokens** (headline) | total tokens of all tool results returned to the agent, counted with the `o200k_base` tokenizer |
| Tool calls | number of calls, by tool name |
| Tokens per call | retrieved tokens ÷ calls, by tool name |
| Found | whether the key file and key symbol(s) appeared in any tool result |
| Signal ratio | the share of retrieved tokens that came from key files |

### 6.2 Accuracy
| Metric | Definition |
|---|---|
| **Score** | mean grade (1 / 0.5 / 0) |
| Correct / partial / wrong | counts |
| Set and chain recall, precision | for 4.2 and 4.3: key symbols named ÷ key size; key symbols named ÷ symbols named |
| Rubric coverage | for 4.5: points covered ÷ total points |
| Found but wrong | the key was retrieved but the answer missed it: a reasoning failure, not a search failure |
| Correct but not found | the answer was right without retrieving the key: memory. Always the case in C0 |

### 6.3 Cost and effort
| Metric | Definition |
|---|---|
| **Total tokens** | the model's own usage counts, input + output, summed over every turn (cached tokens shown separately when reported) |
| **Tokens per correct answer** | total tokens ÷ score. This is the combined efficiency measure |
| Cost per run (USD) | usage × the provider's list prices on the run date |
| Turns | tool rounds before the final answer; turn-cap hits are counted |
| Wall-clock seconds | per run, split into model time and tool time |

### 6.4 Reliability
| Metric | Definition |
|---|---|
| Spread across the 3 repeats | min / median / max of the headline metrics per question |
| Errors | API or tool errors, malformed final answers, turn-cap hits |

### 6.5 Setup cost (reported once, not per question)
Collected for every repository in every run, on the stated hardware and container limits:

| Stage | Metrics |
|---|---|
| Clone | size on disk, file count |
| Structural ingest | wall time, **peak memory** (container `memory.peak`, per ingest), nodes, edges |
| Embedding | chunks, chunks cut by the token cap, links, model load time, embedding time, time per chunk, embedder peak RSS, container peak memory |
| Storage | Neo4j disk growth |

The 2026-11-14 FastAPI run did not record ingest peak memory; every later run does.

## 7. Predictions (committed before running)

| Category | Retrieved tokens | Accuracy |
|---|---|---|
| Lookup | C3 within ±10% of C1. C2 higher than C1 | all of C1, C2 and C3 about equal |
| Callers / impact | C3 below C1 | C3 ≥ C1 |
| Call chains | C3 below C1 | C3 ≥ C1 |
| Ambiguous / unknown names | C3 ≤ C1 | C3 > C1 |
| Explanatory | uncertain | C3 > C1 |
| Overall | C3 has the lowest tokens per correct answer of C1–C3 | C3 ≥ the best of C1 and C2 |

C0 is the memory floor. The C0 score shows how much of each category a model already knows without looking.

**"Best of both worlds" holds** only if both of these are true:
- C3's score is at least as high as the better of C1 and C2 in every category.
- C3's tokens per correct answer is the lowest of C1–C3 overall.

Whatever the outcome, every result is published, including categories where C3 loses.

## 8. Controls

- **The same prompt, settings and answer format** in every condition. Only the tool list differs.
- **Temperature 0.3**, at most 2,048 output tokens per turn, a cap of 14 tool turns.
- **Runs in random order**, 3 at a time. The order seed is recorded.
- **Tools enforced by the harness.** The agent can't reach anything outside its condition's tools.
- **Answer keys outside every path the tools can open.** The harness checks this before each run.
- **Everything pinned:** commit, model IDs, tokenizer, the graph built from the same commit, and the embedding settings, all recorded.
- **The judge never sees** the condition, the model or the tool calls.

## 9. Validation, before any agent runs

1. **Structural keys:** regenerate every key in 4.2 and 4.3 with `keys/fastapi_callgraph.py`, and confirm they match the tables.
2. **Lookup and name keys:** confirm that every file and symbol in 4.1 and 4.4 exists at the commit. These are the ⏳ rows.
3. **Rubric points:** cite a `file:line` for every point in 4.5. Drop or rewrite any point that can't be cited.
4. **Leak check:** no question in 4.4 may contain its key symbol's name. This is checked by script.
5. **Grader self-test:** feeding each key as the answer must grade *correct*, an empty answer must grade *wrong*, and a half answer must grade *partial*. This runs for every question.
6. **Judge calibration:** for each rubric question, three hand-written answers (good, partial, poor) must get the expected grades from the judge before the judge is used.
7. **Dry run:** 1 question × 4 conditions × 1 model. Check that the records are complete and the costs are as estimated.

Results of each step are written to `eval/VALIDATION.md` before the main run starts.

## 10. Threats to validity

| Threat | Mitigation |
|---|---|
| The models already know FastAPI (memorization) | C0 measures it per category. "Correct but not found" is reported |
| The question author's bias | keys derived independently. A pull-request-derived question set is planned |
| The baseline's efficiency drives the result | C1's design is stated, and a "typical defaults" variant is planned |
| The graph is code-only (tree-sitter), so call edges are matched by name | stated. The structural keys use the same name-matching rule |
| Tool defaults (budgets) drive the graph tools' token counts | shipped defaults are used and stated. Tuning is a separate, later experiment |
| One repo, 30 questions, 3 repeats | reported as a pilot. nestjs and more repos follow |
| The provider routes models or changes them | model IDs and dates are recorded. Results are tied to that date |
| Tokenizer differences between models | retrieved tokens use one tokenizer for all. Total tokens use each model's own counts |

## 11. Out of scope for this run

The nestjs balanced set (its keys will come from the TypeScript compiler), cross-repo questions, freshness, caching, and the "typical defaults" baseline variant. These are planned, not part of this run.

## 12. Acknowledgement

Model inference for the agent runs and the judge is provided by Cheaperinference.
