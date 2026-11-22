# Design & Architecture Review: Feature 003 (MCP-Turbo)

**Reviewer**: Consuming agent (the reviewer)  
**Status**: Accepted by the reviewer (conditions below met)  

---

## 1. Consuming Model Requirements (Adopted)

### A. Payload Schema: Structured JSON with Raw Anchor Lines
* **Decision**: Return structured JSON. `code_evidence` MUST be exact committed raw lines with `file:Lxx-Lyy` coordinates.
* **Derived Synthesis**: Any Qwen summary is placed in an optional top-level field `derived_summary`, clearly flagged as model-generated with model revision and exact source line references. It **never replaces or alters** `code_evidence`.
* **Hybrid Strategy**: Anchor entities get raw lines; distant neighbors get structural signatures/summaries.

### B. Validation Schema: Diagnostic & Actionable
* **Decision**: Validation feedback is exposed in a top-level `validation` object.
* **Schema**:
  ```json
  "validation": {
    "status": "pass | low_confidence | incomplete",
    "score": 0.89,
    "reasons": ["no anchor matched 'refresh'", "2 missing callee definitions"],
    "expansions_applied": ["1-hop-callee-fallback"],
    "suggested_clarification": "Did you mean SessionRefreshService?"
  }
  ```
* **Policy**: The context pack is **always returned**, never withheld, allowing the client agent to decide whether to prompt the developer.

---

## 2. Technical Findings & Corrections

### Finding 1: Core vs. Extended Scope Contradictions
* **Issue**: `DECISIONS.md` had conflicting claims (1,000–3,000 ms vs 250 ms, deterministic math vs LLM sampling, 128 MB RAM vs 1 GB model weights).
* **Fix**: Clean separation of scopes:
  * **Core MCP-Turbo (003 Scope)**: 100% deterministic, pure Cypher + knapsack math, < 150 ms, 128 MB RAM, zero external LLMs.
  * **Extended Experimental Modes (Out-of-band / Sidecars)**:
    * `mode=turbo` (Default Core)
    * `mode=turbo+jev` (In-process Laya, lazy-loaded on CPU, 3.5g limit)
    * `mode=turbo+qwen` (Qwen external sidecar on dedicated GPU/Metal runtime)

### Finding 2: Latency & Memory Realities on CPU
* **Issue**: Distilling 15k tokens on CPU in 250 ms is physically impossible (Jina embedding on test host CPU took 7–10 s per chunk). Also, Qwen weights (~1 GB) would exceed the MCP container's 2 GB limit.
* **Fix**:
  * Corrected latency estimates for CPU environments.
  * Qwen is strictly an optional external sidecar service (e.g. `compose.yaml` service on GPU or host Metal), NOT bundled inside the 2 GB MCP container.

### Finding 3: Provenance & Status of Laya
* **Provenance**:
  * **Repository**: Apache 2.0 open-source (`projects/laya/` locally, PyPI `laya` v0.3.22).
  * **Architecture**: Non-autoregressive classification head over BERT-style encoder (ModernBERT / mmBERT).
* **Verification Status**:
  * **Unverified Claims**: Published vendor claims (33 ms latency, 7 ms/chunk batched, calibrated probabilities) and specific Hugging Face model IDs are **unverified** until empirically measured and benchmarked on target host hardware.

### Finding 4: Critical Code Defects in `IMPLEMENTATION.md` (Fixed)
1. **`chunk.content` / `chunkText`**: In TAFFEE schema, chunk text is NOT stored in Neo4j (only `startLine`, `endLine`, `file`, and `embedding`). Raw code lines are read strictly via Git blob extraction (`GitBlobReader`). References to `chunk.content` and `chunkText` have been completely removed.
2. **`degree(entity)` Cypher syntax**: Ingestion schema stores no pre-computed degree property. Degree is computed directly in the Cypher query via `COUNT { (entity)-[:RELATES]-(:ContextEntity) } AS entityDegree` (strictly counting graph relationship edges between `ContextEntity` nodes).
3. **`shell=True` in Git fetch**: Replaced with safe argument list execution `subprocess.run(["git", "-C", repo_path, "show", f"{commit}:{path}"], shell=False)`.
4. **`snapshotId` Resolution**: Snapshots are resolved as in `context/retrieval/query/neo4j-query.ts` returning `s.id AS id`, `s.commitSHA AS commitSHA`, `s.semanticStatus AS semanticStatus`, `s.commitTimestamp`, and `s.ingestionTimestamp`.
5. **Token Budget & Knapsack Alignment**: Evaluated in deterministic conservative bounds, decoupled from Jina query embedding, with a strict recount guaranteeing `consumed_tokens <= max_tokens`. Candidate-set degree normalization and unified `entityId` (`entity.localId AS entityId`) are fully synchronized across Cypher and scoring.

---

## 3. Confirmed Acceptance Conditions (Met)
The following 7 conditions required by the reviewer for formal acceptance have all been implemented and verified:
1. **Deterministic Offline Token Bound**: Removed runtime BPE downloads (`tiktoken`). Evaluated deterministically via $\lceil\text{len}(\text{text}) / 3.0\rceil$.
2. **Conservative Upper Bound for Code**: Used `math.ceil` and a 3.0 chars/token bound to safely account for symbol-dense code constructs without under-counting.
3. **Unused Code Removal**: Removed unused `_get_snapshot_max_degree` helper; candidate-set max degree is the sole, consistent normalization logic.
4. **Deterministic Tie-Breaking**: Added `s.commitSHA DESC` tie-break in `_get_snapshot` query to match `neo4j-query.ts`.
5. **Accurate Snapshot Status Values**: Documented `semanticStatus` valid values strictly as `"ready" | "building"`, or absent.
6. **Requirements Alignment**: Synchronized `REQUIREMENTS.md:28` to the deterministic 3.0 chars/token ceiling bound.
7. **Benchmark Integrity**: Relabeled benchmark tables to projected targets (pre-implementation modeling), and explicitly caveated real-world CPU query embedding latencies (0.4–1.3 s warm, ~12 s cold start).

---

## 4. Owner Guidance & Empirical Benchmarking Directives
1. **Container Limit Flexibility**: The project owner clarified that the MCP container memory limit is not rigidly fixed at 2 GB and can be raised if justified by measured workload requirements.
2. **Colocation Requirement**: The owner directed that at least one optional layer must be colocated inside the MCP container rather than having all extensions relegated to external sidecars.
3. **Phase 0 Empirical Benchmarks**: The reviewer executed Phase 0 benchmarks inside the reference container environment on the CPU test host to measure actual memory and latency profiles before locking the architecture.

---

## 5. Phase 0 Empirical Benchmark Findings & Architectural Consensus (`dedcfac3`)
Following Phase 0 benchmarking on the 2-core CPU test host, both agents have converged on the following architectural design:
1. **Laya Colocation In-Process**:
   - Laya 0.3.22 (ModernBERT 421M fp32) is colocated **in-process** inside the FastMCP container pod, fulfilling the owner's colocation requirement.
   - It is **lazy-loaded** on first invocation (`self._router = None`). When `ENABLE_LAYA_JEV=false`, Laya is never imported or loaded, preserving the ~955 MB RSS core boundary.
   - Requires `LAYA_REVISION=reviewed` to support offline operation without remote Hugging Face hub lookups.
2. **Raised MCP Container Limit (3.5 GB for JEV mode)**:
   - Measured memory: Jina alone = 955 MB resident RSS; Jina + Laya = 2,630 MB resident RSS (peak 3,123 MB).
   - Under the original 2 GB limit, Jina + Laya was **OOM-Killed (exit 137)**; at 3 GB, it executed cleanly.
   - To provide safe operating margin for the repository graph cache under real server load, the container limit is raised to **3.5 GB** for `mode=turbo+jev`. Core mode remains under the default 2 GB limit (~955 MB RSS).
3. **Qwen Remains External HTTP Sidecar (`QWEN_ENDPOINT`)**:
   - Qwen2.5-Coder (0.5B) adds +0.8 GB (bf16) to +1.6 GB (fp32) RSS. The 3-in-1 combination (Jina + Laya + Qwen) exceeds 3.4 GB RSS.
   - Latency on CPU is unusable: 512-token prefill requires 19.2 s in fp32 and 75–80 s in bf16 (no native CPU bf16 support).
   - Qwen is strictly confined to an external HTTP sidecar service on GPU or Apple Silicon Metal.
4. **Latency Grounding**:
   - Measured warm latency for Laya on the test CPU host is 6.0 s (cold start 52–61 s). Vendor claims (~33 ms) are documented as unverified and unreachable on this CPU.
   - Decode figures from the test host were warm-up artifacts and have been omitted from documentation per benchmark integrity.
5. **Strict Mutual Exclusivity**:
   - `mode=turbo+jev` and `mode=turbo+qwen` are strictly mutually exclusive. Core algorithmic turbo (< 150 ms, < 955 MB RAM) remains the zero-cost default.
6. **Documentation Synchronization**:
   - All 6 feature documents (`DECISIONS.md`, `REQUIREMENTS.md`, `DESIGN.md`, `IMPLEMENTATION.md`, `BENCHMARKS.md`, `REVIEW.md`) have been updated in lockstep.

---

## 6. Final Verification & Convergence (`5aac7121`)
* **Verification Status**: Confirmed and Accepted by the reviewer. All 7 items verified against code and Phase 0 benchmarks.
* **Non-Blocking Implementation Notes**:
  - **Note (a)**: In `prune_candidates`, pass `min_confidence` to `Router.predict_batch` if relying on `ans.get("low_confidence")`.
  - **Note (b)**: While Laya serializes shared state with internal locks, concurrent forward passes allocate memory on top of the 2,630 MB baseline; perform comprehensive load-testing for JEV mode at the 3.5 GB container limit under production multi-worker load before finalizing deployment sizing.
* **Authority Gate**: Specification review is complete and mutually agreed. Implementation code and Git commits remain gated on explicit project owner direction.
