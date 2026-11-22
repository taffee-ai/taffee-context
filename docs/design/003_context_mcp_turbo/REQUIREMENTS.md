# Requirements: MCP-Turbo Context Pack Engine

Scope: Server-side context assembly engine exposed as an MCP tool over the existing Neo4j graph and Jina vector store.

## Functional Requirements

1. **Single-Shot MCP Tool Contract**:
   Expose tool `assemble_context_pack` on the FastMCP server with the following schema:
   * `repo` (string, required): Repository ID.
   * `task` (string, required): Developer query or task description (e.g., *"How is OAuth token refresh handled?"*).
   * `max_tokens` (integer, optional, default: `4000`, min: `500`, max: `16000`): Hard cap on the generated context pack payload.
   * `commit` (string, optional): Full 40/64-char commit SHA. Defaults to the latest ready snapshot.

2. **Output Schema (`Trusted Context Pack`)**:
   Return a structured, JSON/Markdown portable payload containing:
   * `metadata`: `repoId`, `commitSHA`, `commitTimestamp`, `ingestionTimestamp`.
   * `budget_accounting`: `requested_tokens`, `consumed_tokens`, `chunks_included`, `entities_included`, `truncated`.
   * `architectural_anchors`: Top matching AST entities (classes, functions, controllers) with signature and location (`file:Lxx-Lyy`).
   * `dependency_chain`: Directed graph edges (`calls`, `imports`, `extends`) connecting the anchor entities.
   * `code_evidence`: Exact committed source lines for the highest-ranked chunks, deduplicated and fitted within `max_tokens`.

3. **Hybrid Algorithmic Ranking**:
   Rank code chunks and AST entities using a combined scoring function:
   $$\text{Score}(e) = \alpha \cdot \text{VectorSimilarity}(q, e) + \beta \cdot \text{GraphCentrality}(e) + \gamma \cdot \text{LexicalMatch}(q, e)$$
   Default weights: $\alpha = 0.50$, $\beta = 0.35$, $\gamma = 0.15$.

4. **Greedy Knapsack Token Packing**:
   * Estimate token counts using a deterministic conservative upper bound $\lceil\text{len}(\text{text}) / 3.0\rceil$ (3.0 chars/token to safely bound symbol-heavy code without runtime network tokenizer downloads).
   * Pack chunks and relationship definitions into the context pack in priority order until `max_tokens` is reached.
   * Never exceed `max_tokens` (`consumed_tokens <= max_tokens` strictly guaranteed).

5. **Commit Pinning & Snapshot Immutability**:
   * Context is strictly derived from the exact requested commit snapshot.
   * Uncommitted or working-tree changes are never mixed into the pack.

6. **Optional JEV Layer (Laya Integration)** (`ENABLE_LAYA_JEV=true`):
   * Colocated **in-process** inside the FastMCP container via lazy loading on first call (core mode never incurs the 1.7 GB memory penalty).
   * System 1 non-autoregressive intent routing to dynamically select the Cypher traversal strategy. Note: vendor timing claims (~33 ms) are unverified and unreachable on 2-core CPU test host (measured warm latency: 6.0 s).
   * Batch candidate pruning using typed `noul` decisions to eliminate noise before packing.
   * Offline requirement: runs with `LAYA_REVISION=reviewed` to bypass Hugging Face hub `main` ref lookup.
   * Container limit: requires raised container memory limit of **3.5 GB** for `mode=turbo+jev` (measured 2,630 MB resident RSS, peak 3,123 MB; OOM-killed exit 137 under default 2 GB limit).
   * Graceful fallback to pure algorithmic core if disabled, import/load fails, or uninstalled.
   * Mutually exclusive with Qwen distillation (`mode=turbo+jev` vs `mode=turbo+qwen`); no combined mode is defined.

7. **Optional SLM Distillation Layer (Qwen-Coder Integration)** (`ENABLE_QWEN_DISTILLER=true`):
   * Pluggable local SLM (`Qwen2.5-Coder-0.5B` / `1.5B` via local HTTP endpoint `QWEN_ENDPOINT`) running as an external service on dedicated GPU or host Metal runtime (outside the MCP container).
   * Compresses 10,000–20,000 raw tokens of AST and code chunks into a ~600-token high-density architectural brief in an isolated `derived_summary` field.
   * Achieves 90%+ token reduction for external frontier models (the client model) and slashes cloud TTFT.
   * Graceful fallback to returning raw uncompressed context pack if disabled, unreachable, or on timeout (>2.0s).
   * Mutually exclusive with Laya JEV (`mode=turbo+qwen` vs `mode=turbo+jev`).

## Non-Functional Requirements

1. **Latency (Core Mode)**:
   * Total response time for `assemble_context_pack` in core algorithmic mode MUST be **< 1000 ms** on repositories with up to 5,000 AST nodes (subject to local CPU embedding bounds).
   * Neo4j traversal and vector index query MUST complete in **< 200 ms**.
2. **Determinism (Core Mode)**:
   * Identical `(repo, commit, task, max_tokens)` requests in core mode MUST return bit-identical context packs. Zero non-deterministic LLM sampling.
3. **Resource Footprint**:
   * **Core Mode**: In-memory graph processing per call MUST not exceed **128 MB RAM**; total process resident RSS has a measured baseline of about **1 GB** (~950–970 MB live, 955 MB lab reading), running safely within the default **2 GB** MCP container limit on CPU.
   * **JEV Mode (`mode=turbo+jev`)**: Container limit is raised to **3.5 GB** (measured resident RSS 2,630 MB, adding headroom for graph cache). Runs completely on CPU with `LAYA_REVISION=reviewed`.
   * **Qwen Distillation**: Runs as external HTTP service on GPU/Metal; does not run inside the MCP container.
