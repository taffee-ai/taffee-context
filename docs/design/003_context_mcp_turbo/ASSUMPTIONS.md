# Assumptions: Feature 003 (MCP-Turbo)

Why this file exists: several decisions in this feature rest on guesses, projections or vendor claims. They are written down here so that a reader of the code or the design can tell **what was assumed, where it came from, and whether it has been tested**. An assumption is not a fact because it appears in a design document.

**Last updated**: 2026-11-15. Evidence is limited to code facts, fixtures and model-only measurements. Everything that depends on how the pack performs on real repositories is marked unverified until it is measured on public repositories (roadmap E10).

Status: ✅ Verified · 🟡 Partly verified · ❔ Unverified · 🔴 Invalidated or known to fail · ⚪ Owner decision.

| ID | Assumption | Status | Evidence | What would prove it wrong |
|---|---|---|---|---|
| A-001 | A weak test laptop is useful only for relative comparisons, never as a production benchmark | ⚪ Owner decision | Owner directive | n/a (policy) |
| A-002 | Core pack latency is under 150 ms and total under 1000 ms on production-grade hardware | ❔ Unverified | Not measured on public repositories or production hardware | A timed run on public repositories |
| A-003 | Stage timings in the design (embed about 40 ms, Cypher 45 to 80 ms, rank 10 ms, Git 25 to 45 ms) | ❔ Unverified | Design estimates only | Per-stage timings on public repositories |
| A-004 | `ceil(len/3.0)` is a safe upper bound for the token count of code in the consuming model | ❔ Unverified | Chosen so the budget needs no tokenizer and stays deterministic; not measured against a real tokenizer | Real tokens per character on public code |
| A-005 | Ranking by vector + log-normalized `RELATES` degree + lexical match surfaces the right code | ❔ Unverified | Default weights are vector 0.70, degree 0.15, lexical 0.15. No public labelled relevance set has been run against the pack | A labelled public question set |
| A-006 | Whole 150-line chunks are a workable packing unit, including small budgets | ❔ Unverified | Chunking is verified for embedding (feature 002), not as a packing unit | TC-02 failing at small budgets |
| A-007 | The top-k of the shared vector index contains enough of the target repository's chunks | 🔴 Known to fail when crowded | The index is shared across snapshots, so other repositories can crowd the target out. The pack uses a larger fetch plus an exact-scan fallback | Crowding test on many public repositories |
| A-008 | Snapshot id equals `JSON.stringify([repoId, sha])` | ✅ Verified | `context/types.ts` and the loader code | n/a |
| A-009 | Laya 0.3.22 installs and runs beside transformers 4.57.1 and torch 2.8.0+cpu | ✅ Verified | Installed with `--no-deps`, pins unchanged; `Router().predict` answered a sample text. Offline use needs `LAYA_REVISION=reviewed` | A failure in a clean build |
| A-010 | Jina plus Laya fit in a 3.5 GB container; core mode stays in 2 GB | 🟡 Partly verified | Model-only measurement: Jina alone about 955 MB resident; Jina + Laya about 2,630 MB, OOM-killed at a 2 GB limit, runs at 3 GB. Not measured under real server load on public data | Memory under load on public repositories |
| A-011 | Laya's published speeds (about 33 ms per decision) and calibrated probabilities | ❔ Unverified vendor claim | On a 2-core laptop CPU one 3-question predict took about 6.0 s warm. The vendor's hardware is not stated, so the figures are not comparable | Timing on stated hardware |
| A-012 | JEV mode makes about three sequential Laya passes per request (route, prune, validate) | 🟡 From the code | The code calls route, prune and validate; their combined cost on public data is not measured | End-to-end timing on public repositories |
| A-013 | A small local model (Qwen2.5-Coder-0.5B) can condense context to about 600 tokens with acceptable accuracy | ❔ Unverified | No quality test. Model-only cost on a 2-core CPU: a 512-token prompt takes 19.2 s (fp32) or 75 to 80 s (bf16); the service needs about 2.2 GiB resident | A quality test on public repositories |
| A-014 | A multi-call agent needs 4 to 18 turns where the pack needs 1 | ❔ Unverified, illustrative | Figures in the original design are illustrative; no public run behind them | An agent eval on public repositories |
| A-015 | Pack output is byte-identical for identical calls | 🟡 Partly verified | The pinned Jina model gives bit-identical vectors across machines (feature 002); the unit tests check deterministic scoring | A repeat-call test on public repositories |
| A-016 | The repositories used for testing are representative of real use | ❔ Unverified | Only fixtures and two public repositories (FastAPI, NestJS) are in scope | Results that do not generalise |
| A-017 | Reading code from Git at the snapshot commit returns the indexed lines, and is fast | 🟡 Partly verified | `read_code` serves committed lines with `git show`; the public eval used it on FastAPI. Speed from a local clone is not a remote-provider estimate | A remote Git provider |
| A-018 | A cosine similarity of at least 0.3 separates relevant chunks from noise | 🔴 Invalidated | Feature 002's own off-topic fixture query scored 0.627, so 0.3 filters nothing | n/a |
| A-019 | The exact-scan fallback stays affordable as the number of repositories grows | ❔ Unverified | Its cost depends on the target snapshot's chunk count (bounded at 20,000); how often it runs grows with repositories | Fallback latency near the bound |
| A-020 | Degree centralities are pre-computed at ingestion (original design claim) | 🔴 Invalidated | Nothing stores a degree property; the pack computes it per query with a `COUNT {}` subquery | n/a |
| A-021 | The single-shot pack makes the whole agent task faster and cheaper (original thesis: about 10 times faster, 80 to 90% fewer tokens, recall 94 to 98%) | ❔ Unverified, doubtful | Never shown. Internal tests did not support it, and the pack was left out of the public eval. See [README.md](README.md) | A public agent eval with and without the pack |
| A-022 | A structural graph plus vector similarity is enough to choose the right anchors and dependency chain without an ontology of entity roles | ❔ Unverified, doubtful | Framework roles (controllers, guards, injectable services) are not extracted; the chain is built from generic `RELATES` edges | A labelled public question set |
