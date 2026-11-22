# FastAPI balanced question set

The harness reads the questions and keys from [fastapi-balanced.jsonl](fastapi-balanced.jsonl). This page is a readable copy, generated from that file; keep the two in sync. The design, categories and conditions are in [../DESIGN.md](../DESIGN.md).

- **Repo and commit:** fastapi/fastapi at `913c68062c8990ea2c00d856d81b7e2383485155`.
- **Where the keys come from:** independently of the graph. Structural keys were derived with Python's own parser (`ast`): for each call, the function or method that encloses it. Every key was checked against the code at this commit.

## Grading

| Type | Correct | Partial | Wrong |
|---|---|---|---|
| lookup | names the key file and symbol | right file, wrong or missing symbol | wrong file |
| set / chain | names every key symbol, with at most one extra | names at least half the key symbols | names fewer than half |
| rubric | a separate judge model scores at least 80% of the points as covered | at least 50% | less than 50% |

## Questions (30: 6 lookup, 6 callers, 6 chain, 6 ambiguous, 6 explanatory)

### lookup

| ID | Type | Question | Key |
|---|---|---|---|
| fb-01 | lookup | Which class represents a file uploaded in a request? | `fastapi/datastructures.py` · `UploadFile` |
| fb-02 | lookup | Which function renders the HTML page for the interactive Swagger UI docs? | `fastapi/openapi/docs.py` · `get_swagger_ui_html` |
| fb-03 | lookup | What is the default exception handler for HTTPException? | `fastapi/exception_handlers.py` · `http_exception_handler` |
| fb-13 | lookup | Which function renders the ReDoc documentation page? | `fastapi/openapi/docs.py` · `get_redoc_html` |
| fb-14 | lookup | Which class reads an API key from a request header? | `fastapi/security/api_key.py` · `APIKeyHeader` |
| fb-15 | lookup | Which class implements HTTP Basic authentication? | `fastapi/security/http.py` · `HTTPBasic` |

### callers

| ID | Type | Question | Key |
|---|---|---|---|
| fb-04 | set | Which functions or methods in the fastapi package (not tests or docs) call solve_dependencies directly? Name the enclosing function or method of every call site. | `solve_dependencies`, `_solve_dependencies`, `get_request_handler`, `get_websocket_app` |
| fb-06 | set | If the signature of get_dependant changed, which functions in the fastapi package call it directly and would need updating? | `get_dependant`, `get_parameterless_sub_dependant`, `solve_dependencies`, `_build_dependant_with_parameterless_dependencies` |
| fb-10 | set | Which of FastAPI's built-in exception handlers pass validation errors through jsonable_encoder? | `request_validation_exception_handler`, `websocket_request_validation_exception_handler` |
| fb-16 | set | Which security classes split the Authorization header using get_authorization_scheme_param? Name each class. | `HTTPBase`, `HTTPBasic`, `HTTPBearer`, `HTTPDigest`, `OAuth2AuthorizationCodeBearer`, `OAuth2PasswordBearer` |
| fb-17 | set | Which functions in the fastapi package call create_model_field? | `_get_body_field`, `analyze_param`, `_populate_api_route_state` |
| fb-18 | set | Which methods (including decorators) register a WebSocket route by calling add_api_websocket_route? Give them as Class.method. | `FastAPI.add_api_websocket_route`, `FastAPI.websocket`, `APIRouter.websocket` |

### chain

| ID | Type | Question | Key |
|---|---|---|---|
| fb-05 | chain | Trace the call chain from the FastAPI application's openapi() method down to the function that builds the metadata (summary, description, operationId) for one path operation. List every function in the chain, in order. | `openapi` → `get_openapi` → `get_openapi_path` → `get_openapi_operation_metadata` |
| fb-07 | chain | Starting at APIRoute.get_route_handler, which functions does a request pass through before the endpoint function itself is called? List them in order. | `get_route_handler` → `get_request_handler` → `run_endpoint_function` |
| fb-19 | chain | Starting at FastAPI.setup, through which functions is the Swagger UI HTML page produced? List them in order. | `setup` → `swagger_ui_html` → `get_swagger_ui_html` |
| fb-20 | chain | Starting at get_dependant, through which functions does one endpoint parameter pass before a model field is created for it? List them in order. | `get_dependant` → `analyze_param` → `create_model_field` |
| fb-21 | chain | Starting at get_openapi, through which functions does FastAPI go to build the parameters list of one operation? List them in order. | `get_openapi` → `get_openapi_path` → `_get_openapi_operation_parameters` |
| fb-22 | chain | Starting at solve_dependencies, through which functions do form fields pass before they are extracted from the request body? List them in order. | `solve_dependencies` → `request_body_to_args` → `_extract_form_body` |

### ambiguous

| ID | Type | Question | Key |
|---|---|---|---|
| fb-08 | lookup | FastAPI has several functions whose names start with get_openapi. Which one builds the metadata (summary, description, operationId, tags) for a single operation? | `fastapi/openapi/utils.py` · `get_openapi_operation_metadata` |
| fb-09 | lookup | Where are form fields (multipart or URL-encoded) pulled out of the request body and matched to the endpoint's parameters? | `fastapi/dependencies/utils.py` · `_extract_form_body` |
| fb-23 | lookup | Where does FastAPI detect duplicate operation IDs and warn about them? | `fastapi/openapi/utils.py` · `get_openapi_operation_metadata` |
| fb-24 | lookup | Where are the routes for the interactive docs and the OpenAPI JSON added to the application? | `fastapi/applications.py` · `setup` |
| fb-25 | lookup | Where are the parameter names extracted from a path template such as /items/{item_id}? | `fastapi/utils.py` · `get_path_param_names` |
| fb-26 | lookup | Where is a dependency written as a plain (non-async) function run in a worker thread? | `fastapi/dependencies/utils.py` · `solve_dependencies` |

### explanatory

| ID | Type | Question | Key |
|---|---|---|---|
| fb-11 | rubric | Explain how FastAPI resolves a dependency that itself has sub-dependencies, including what happens when the same dependency is used twice in one request. | 5 points, listed below |
| fb-12 | rubric | Explain what happens from the moment a request reaches a path operation until the response is sent. | 6 points, listed below |
| fb-27 | rubric | Explain how FastAPI produces the OpenAPI schema for an application. | 6 points, listed below |
| fb-28 | rubric | Explain what APIRouter.include_router does when you include a router with a prefix. | 5 points, listed below |
| fb-29 | rubric | Explain how a request validation error becomes an HTTP response in FastAPI. | 5 points, listed below |
| fb-30 | rubric | Explain how OAuth2PasswordBearer obtains the token from a request, and what it does when the token is missing. | 5 points, listed below |

## Rubric points

**fb-11.** Explain how FastAPI resolves a dependency that itself has sub-dependencies, including what happens when the same dependency is used twice in one request.

- get_dependant builds a tree of dependencies (a Dependant) from the endpoint's and each dependency's signature, before requests arrive
- solve_dependencies resolves the tree recursively, solving sub-dependencies before the dependency that needs them
- results are cached for the duration of one request (a dependency cache), so a dependency used twice runs once
- use_cache=False on Depends opts a dependency out of that cache
- dependency overrides (app.dependency_overrides) can replace a dependency at resolution time

**fb-12.** Explain what happens from the moment a request reaches a path operation until the response is sent.

- APIRoute.get_route_handler uses get_request_handler to build the ASGI handler for the route
- the request body is read and parsed (JSON, or form data for form parameters)
- solve_dependencies validates parameters and body and runs dependencies; validation errors raise RequestValidationError, which becomes a 422 response
- run_endpoint_function calls the endpoint, running a plain def endpoint in a threadpool
- serialize_response validates and serializes the return value against the response model
- the response class builds the response, with any background tasks attached

**fb-27.** Explain how FastAPI produces the OpenAPI schema for an application.

- FastAPI.openapi() builds the schema once and caches it in openapi_schema, rebuilding it when the routes change
- it calls get_openapi with the application's routes and metadata
- get_openapi walks the routes and calls get_openapi_path for each one
- parameters, request bodies and responses become schema entries, with shared models collected as components
- security schemes are collected from each operation's security dependencies
- the schema is served at openapi_url by a route that setup adds

**fb-28.** Explain what APIRouter.include_router does when you include a router with a prefix.

- it refuses to include a router into itself, or into a router that the included router already contains
- it validates the prefix: it must start with '/' and must not end with '/'
- it does not copy the included router's routes; it builds an include context holding the prefix, tags, dependencies, responses, callbacks and the unique-ID function
- it appends a single _IncludedRouter that wraps the original router together with that context, so routes are resolved through the wrapper when requests are matched
- it carries over the included router's startup/shutdown handlers and merges its lifespan context

**fb-29.** Explain how a request validation error becomes an HTTP response in FastAPI.

- validation errors are collected while the parameters and body are solved (solve_dependencies returns them)
- get_request_handler raises RequestValidationError when there are errors
- the application registers request_validation_exception_handler as the default handler for RequestValidationError
- that handler returns a 422 response whose body is the errors encoded with jsonable_encoder
- the default can be replaced with a custom handler through exception_handlers

**fb-30.** Explain how OAuth2PasswordBearer obtains the token from a request, and what it does when the token is missing.

- its __call__ reads the Authorization header from the request
- get_authorization_scheme_param splits the header into scheme and value
- it checks that the scheme is bearer (case-insensitive)
- if the header is missing or not bearer and auto_error is set, it raises a 401 HTTPException with a WWW-Authenticate: Bearer header; with auto_error off it returns None
- it returns the token string and does not validate the token itself

## Where each key was checked

| ID | Source |
|---|---|
| fb-01 | fastapi/datastructures.py class UploadFile |
| fb-02 | fastapi/openapi/docs.py def get_swagger_ui_html |
| fb-03 | fastapi/exception_handlers.py async def http_exception_handler |
| fb-13 | fastapi/openapi/docs.py:197 |
| fb-14 | fastapi/security/api_key.py:147 |
| fb-15 | fastapi/security/http.py class HTTPBasic |
| fb-04 | keys/fastapi_callgraph.py callers solve_dependencies |
| fb-06 | keys/fastapi_callgraph.py callers get_dependant |
| fb-10 | keys/fastapi_callgraph.py callers jsonable_encoder (fastapi/exception_handlers.py) |
| fb-16 | keys/fastapi_callgraph.py callers get_authorization_scheme_param |
| fb-17 | keys/fastapi_callgraph.py callers create_model_field |
| fb-18 | keys/fastapi_callgraph.py callers add_api_websocket_route |
| fb-05 | keys/fastapi_callgraph.py callers get_openapi, get_openapi_path, get_openapi_operation_metadata |
| fb-07 | keys/fastapi_callgraph.py callers get_request_handler, run_endpoint_function |
| fb-19 | keys/fastapi_callgraph.py path setup get_swagger_ui_html |
| fb-20 | keys/fastapi_callgraph.py callers analyze_param, create_model_field |
| fb-21 | keys/fastapi_callgraph.py callers get_openapi_path, _get_openapi_operation_parameters |
| fb-22 | keys/fastapi_callgraph.py callers request_body_to_args, _extract_form_body |
| fb-08 | fastapi/openapi/utils.py:279 |
| fb-09 | fastapi/dependencies/utils.py:1137 |
| fb-23 | fastapi/openapi/utils.py:291 (inside get_openapi_operation_metadata, line 279) |
| fb-24 | fastapi/applications.py:1120-1140 |
| fb-25 | fastapi/utils.py:43 |
| fb-26 | keys/fastapi_callgraph.py callers run_in_threadpool (solve_dependencies) |
| fb-11 | fastapi/dependencies/utils.py get_dependant; solve_dependencies (recursive call :726); use_cache :312; dependency_cache :668; dependency_overrides_provider :678 |
| fb-12 | fastapi/routing.py get_route_handler; get_request_handler :397; request.form() :455; RequestValidationError :477; run_endpoint_function :363 (run_in_threadpool); serialize_response :320; background tasks :752 |
| fb-27 | fastapi/applications.py:1085-1118 (openapi, cache, routes_version), :1135 (setup add_route); fastapi/openapi/utils.py get_openapi :577, get_openapi_path calls :623/:643, _get_openapi_security_definitions :132/:341 |
| fb-28 | fastapi/routing.py:3373-3425 (APIRouter.include_router), _IncludedRouter :1645, _RouterIncludeContext.for_include |
| fb-29 | fastapi/routing.py:477; fastapi/applications.py:1002; fastapi/exception_handlers.py:20-25 |
| fb-30 | fastapi/security/oauth2.py:104-112 (__call__), :401-420 (make_not_authenticated_error, 401, WWW-Authenticate Bearer) |
