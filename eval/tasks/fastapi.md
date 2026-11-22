# FastAPI question set

The harness reads the questions and answer keys from [fastapi.jsonl](fastapi.jsonl). This page is a readable copy; keep the two in sync.

- **Repo:** https://github.com/fastapi/fastapi
- **Commit:** `913c68062c8990ea2c00d856d81b7e2383485155`
- **Writing the questions:** each one describes behaviour without naming the function or file. Every key was checked against the code at this commit.
- **Grading:** an answer is *correct* if it names every key file and the key symbol exactly. It's *partial* if it names the right file but the wrong or a missing symbol, and *wrong* otherwise.

| ID | Question | Key file | Key symbol |
|---|---|---|---|
| fastapi-01 | When a request arrives, which function walks an endpoint's declared dependencies, calls each one (including sub-dependencies) and collects their values and any validation errors? | `fastapi/dependencies/utils.py` | `solve_dependencies` |
| fastapi-02 | Before any request arrives, which function inspects an endpoint function's signature and builds the internal description of its parameters and dependencies? | `fastapi/dependencies/utils.py` | `get_dependant` |
| fastapi-03 | Which function builds the ASGI request handler for a path operation, i.e. the code that reads the request body, runs the dependencies and raises the error when request validation fails? | `fastapi/routing.py` | `get_request_handler` |
| fastapi-04 | After an endpoint function returns, where is the return value validated against the declared response model and serialized? | `fastapi/routing.py` | `serialize_response` |
| fastapi-05 | Which function generates the complete OpenAPI document for an application? | `fastapi/openapi/utils.py` | `get_openapi` |
| fastapi-06 | What is the default exception handler that turns a request validation error into a 422 JSON response? | `fastapi/exception_handlers.py` | `request_validation_exception_handler` |
| fastapi-07 | Which function converts arbitrary Python objects (Pydantic models, dataclasses, datetimes, enums and so on) into JSON-compatible data? | `fastapi/encoders.py` | `jsonable_encoder` |
| fastapi-08 | Which class extracts the bearer token from the Authorization header for the OAuth2 password flow? | `fastapi/security/oauth2.py` | `OAuth2PasswordBearer` |
| fastapi-09 | When one router is mounted into another router or into the app with a prefix, which method copies its routes over? | `fastapi/routing.py` | `include_router` |
| fastapi-10 | Where is the default unique operation ID for a route generated? | `fastapi/utils.py` | `generate_unique_id` |
