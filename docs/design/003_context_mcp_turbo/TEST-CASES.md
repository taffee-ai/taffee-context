# Test Cases: MCP-Turbo Context Pack Engine

### TC-01: Standard Context Pack Assembly
* **Given**: An ingested, ready repository (`demo-shop` at committed HEAD).
* **When**: Caller issues `assemble_context_pack(repo="demo-shop", task="validate widget access", max_tokens=4000)`.
* **Then**:
  * Response returns HTTP 200 with JSON payload.
  * `budget_accounting.consumed_tokens` $\le 4000$.
  * `architectural_anchors` contains `widget-access.guard.ts` or related entities.
  * `dependency_chain` contains valid `calls` / `imports` edges.
  * Wall time $< 1000$ ms.

### TC-02: Hard Token Budget Enforcement
* **Given**: A large codebase where search matches 20+ chunks (~12,000 tokens total).
* **When**: Caller sets `max_tokens=1000`.
* **Then**:
  * Response contains the top 1–2 anchor symbols and the single most decisive code snippet.
  * Total consumed tokens $\le 1000$.
  * Output includes `truncated: true` in budget accounting.

### TC-03: Commit Isolation & Snapshot Scoping
* **Given**: Two distinct snapshots of `demo-web` (Commit SHA `A` and Commit SHA `B`).
* **When**: Caller explicitly requests `commit=A`.
* **Then**:
  * Every returned AST entity and code chunk has `snapshotId` matching Commit `A`.
  * Zero entities or chunks from Commit `B` appear in results.

### TC-04: Transitive Caller/Callee Graph Linkage
* **Given**: Fixture repository with `top -> caller -> callee`.
* **When**: Caller asks *"How is callee invoked?"*.
* **Then**:
  * `dependency_chain` includes `caller -> callee` and `top -> caller`.
  * Context pack includes line ranges for both `caller` and `callee`.

### TC-05: Off-Topic / Low-Confidence Match Query (Reduced Pack)
* **Given**: A valid repository.
* **When**: Caller queries with off-topic terms (*"quantum physics gravity simulation"*).
* **Then**:
  * Response never withholds context completely when candidates exist; returns a bounded reduced pack ($\le 2$ anchors, $\le 1$ code chunk).
  * `validation.status` is set to `"low_confidence"` with explicit reasons explaining the weak lexical/semantic margin.
  * Does not crash; bounds token expenditure while preserving best-effort candidate evidence.

### TC-06: Parameter Clamping & Validation
* **Given**: Server running.
* **When**: Caller supplies `max_tokens=50000` (exceeds cap) or `max_tokens=50` (below min).
* **Then**:
  * Server clamps values to supported range ($[500, 16000]$).
  * Missing `repo` or nonexistent repo returns explicit error message.

### TC-07: Authentication & Rate Limiting
* **Given**: MCP server with token authentication enabled.
* **When**: Caller invokes tool with missing or invalid bearer token.
* **Then**: Server returns 401 Unauthorized; zero graph data is leaked.

### TC-08: Path Traversal & Injection Defense
* **Given**: Caller submits malicious input `task="../../../../etc/passwd"`.
* **When**: Tool processes query.
* **Then**:
  * Parameter is sanitized; zero file system directory traversal occurs.
  * Only committed Git object data is read.
