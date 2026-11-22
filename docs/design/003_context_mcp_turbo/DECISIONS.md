# Architectural Decisions: MCP-Turbo Context Pack Engine

## 1. Core Engine: Pure Algorithmic Ranking (Baseline Scope)
* **Decision**: The baseline core engine of MCP-Turbo (Feature 003) assembles and ranks the context pack using pure graph mathematics (vector cosine similarity + degree centrality + lexical AST matching) without running an LLM in the hot path.
* **Rationale**:
  * **Speed**: Pure graph Cypher and matrix math execute in **< 150 ms** on CPU.
  * **Determinism**: Graph algorithms guarantee 100% reproducible results for the same commit, critical for enterprise auditability and caching.
  * **Zero Hallucination**: Graph extraction is mathematically grounded in the AST; code lines are read directly from committed Git blobs.
  * **Memory Bound**: Operates within 128 MB RAM per request inside the standard 2 GB MCP container.

## 2. Single-Pass Unified Cypher Pipeline
* **Decision**: Execute vector similarity search, entity resolution, and neighbor graph expansion in a single Cypher query transaction rather than multiple sequential database calls.
* **Rationale**: Eliminates multiple network round-trips and serialization overhead between the FastMCP Python server and the Neo4j instance.

## 3. Greedy Knapsack Token Budgeting with Raw Evidence Preservation
* **Decision**: Pack context items hierarchically:
  1. Primary anchor symbol definitions and signatures (Highest priority).
  2. Direct 1-hop caller/callee relationships.
  3. Highest-similarity source code chunk bodies.
  4. 2-hop neighborhood context (if tokens remain).
* **Consuming Model Constraint**: `code_evidence` MUST always contain raw committed source lines with `file:Lxx-Lyy` coordinates. Derived summaries NEVER replace or overwrite raw evidence.

## 4. Reading Code via Commit-Pinned Git Blobs
* **Decision**: Retrieve source lines directly from the Git object store at the snapshot's commit SHA (`git show <sha>:<path>`) using safe subprocess execution (`shell=False`).
* **Rationale**: Eliminates working-tree corruption, ensures read-only safety, avoids command injection, and allows instantaneous multi-branch context assembly.

## 5. Optional System 1 JEV Layer (Laya Integration — In-Process Colocation)
* **Decision**: Support an optional System 1 JEV (Judgment / Evaluation / Verification) layer via **Laya** (`ENABLE_LAYA_JEV=true`), colocated **in-process** inside the FastMCP container.
* **Provenance & Specs**:
  * **Source**: Apache 2.0 open-source (`projects/laya/` locally, PyPI `laya` v0.3.22, Hugging Face `convaiinnovations/laya`).
  * **Model**: 421M ModernBERT-large / 322M mmBERT-base non-autoregressive classification head (fp32 checkpoint ~2.3 GB on disk).
  * **Process Architecture**: Colocated in-process in the MCP container via **lazy loading** (`self._router = None`, instantiated only on first call when `ENABLE_LAYA_JEV=true`). Core mode never loads Laya weights and never incurs the ~1.7 GB memory penalty.
  * **Offline Execution**: Requires `LAYA_REVISION=reviewed` to bypass Hugging Face hub `main` ref lookup in offline/airgapped environments.
  * **Empirical Memory & Container Limit**:
    * Phase 0 test host measurements: Jina alone = 955 MB resident RSS (peak 1,239 MB); Jina + Laya = 2,630 MB resident RSS (peak 3,123 MB).
    * Under the default 2 GB container limit, Jina + Laya is **OOM-Killed (exit 137)**. At a 3 GB limit, it runs cleanly.
    * Container Limit Decision: The MCP container memory limit is raised from 2 GB to **3.5 GB** for `mode=turbo+jev` to provide headroom over the 2,630 MB resident RSS for the repository graph cache under real load (not yet tested under production server load). Core mode remains default within the original 2 GB boundary (~955 MB RSS).
  * **Empirical Latency on Test CPU**:
    * Measured on 2-core/4-thread CPU test host: warm latency for 3 questions (~270-char ticket) is **6.0 s** (first call including load takes 52–61 s).
    * Published vendor claim (~33 ms single forward pass) is on unspecified hardware; it is **unverified** and **not reachable** on this CPU test host.
  * **Mutual Exclusivity**: `mode=turbo+jev` and `mode=turbo+qwen` are strictly mutually exclusive; no combined 3-in-1 mode is supported (three-in-one footprint exceeds 3.4 GB).
* **Validation Policy**: Emits top-level `validation: {status, score, reasons[], expansions_applied, suggested_clarification}`. The context pack is **always returned** to the consuming model even on low confidence, never withheld.

## 6. Optional Local SLM Synthesis (Qwen Sidecar — External Hardware Mode)
* **Decision**: Support an optional local SLM synthesis service (`ENABLE_QWEN_DISTILLER=true`) running `Qwen2.5-Coder-0.5B` or `1.5B`.
* **Hardware & Process Boundary**:
  * **External Service**: Qwen does NOT run inside the MCP container. It runs as an **external HTTP sidecar service** (`compose.yaml` via `QWEN_ENDPOINT`) on dedicated GPU or Apple Silicon Metal runtime.
  * **CPU Infeasibility**: Measured on CPU test host: 512-token prefill takes 19.2 s in fp32 and 75–80 s in bf16 (CPU lacks native bf16). Sub-second distillation of 15k tokens is impossible on CPU; it requires Metal/CUDA hardware acceleration.
  * **Memory Isolation**: Adding Qwen to the MCP container adds +0.8 GB (bf16) to +1.6 GB (fp32) RSS, and combining Jina + Laya + Qwen requires > 3.4 GB RSS. Keeping Qwen external avoids container bloat.
  * **Payload Isolation**: Model synthesis is strictly isolated into an optional top-level `derived_summary` field stamped with model revision and line references; it never mutates `code_evidence`.
  * **Mutual Exclusivity**: Mutually exclusive with `mode=turbo+jev`. Core turbo remains the default, 100% deterministic pure Cypher + knapsack (< 150 ms, < 955 MB RAM).
