# Assumptions: Feature 001 (structural code graph)

Why this file exists: decisions in this feature rest on assumptions, some tested and some not. They are recorded here so an agent reading the code or the design can tell what was assumed, where it came from, and whether it has been verified. Evidence comes from `docs/design/verification.md`.

**Maintained by**: The reviewer only. **Last updated**: 2026-11-23

Status: ✅ Verified · 🟡 Partly verified · ❔ Unverified · 🔴 Invalidated or known to fail · ⚪ Owner decision. Test-host numbers describe an old weak test laptop and are never production benchmarks.

| ID | Assumption | Status | Evidence and source | What would prove it wrong |
|---|---|---|---|---|
| A-001 | Graphify 0.9.51 in `--code-only` mode (tree-sitter, no LLM) gives an adequate structural graph | 🟡 Partly verified | FastAPI and NestJS ingested to `ready` (the validator rejects dangling edges and duplicate ids). No comparison with another extractor's counts | An external baseline showing missing entities or edges |
| A-002 | Edge direction is source to target, with calls running caller to callee | 🟡 Partly verified | Checked on a 3-function fixture (callers and callees returned the right way round); the public eval's caller questions on FastAPI rely on it. Not diffed edge by edge | A mismatch found in a wider diff against Graphify's own graph |
| A-003 | A node's `sourceLocation` has the form `L<number>` for its start line | 🟡 Partly verified | Feature 002 links entities to chunks with it; malformed values are skipped. Other formats were not catalogued | Entities with missing or different formats |
| A-004 | The same commit and extractor version give the same graph, so snapshots can be immutable | ✅ Verified | Repeat ingest returns `unchanged` with identical graph and artifact hashes; a different content for the same commit is refused | Non-deterministic extractor output |
| A-005 | Indexing a clean checkout of the exact commit is what we want, with untracked files excluded | ✅ Verified | Live test 6: exact-commit extraction, untracked files not seen, symlinks refused | n/a |
| A-006 | The bounds (50,000 nodes, 200,000 edges, 32 MiB of Graphify output) are large enough | 🟡 Partly verified: NestJS, the largest public repository ingested (15,185 nodes, 36,714 edges), is under the 50,000 and 200,000 bounds | The 32 MiB bound and submodule refusal have no test | A larger repository hitting a bound |
| A-007 | Loading a snapshot in one write transaction with a 30 s timeout is safe | 🟡 Partly verified: NestJS (15,185 nodes, 36,714 edges) ingested end to end in 88.4 s with the size-based timeout | Behaviour near the bounds is untested | A large snapshot timing out |
| A-008 | `verify` (stored hash, artifact hash and counts) is enough to detect a tampered snapshot | 🔴 Invalidated | A node's `label` edited in Neo4j without changing counts was **not** detected. Fixing it means recomputing the hash from stored properties | Already shown wrong (see `docs/design/verification.md`) |
| A-009 | Code-only extraction covers the TypeScript, JavaScript and Python used here | 🟡 Partly verified | Worked on FastAPI at `913c68062c89` (9,342 nodes, 18,919 edges) and NestJS at `2731c18054fb` (15,185 nodes, 36,714 edges), ingested 2026-11-14 for the public eval. Dynamic calls, reflection and generated code are not captured, and calls from inside nested functions are missed | Repositories relying heavily on dynamic dispatch |
| A-010 | Ingest times and memory measured on the test host (59.2 s for FastAPI, 88.4 s for NestJS; peak memory was not recorded) apply only to that host | ⚪ Owner decision | Test host is never a production benchmark | n/a (policy) |
