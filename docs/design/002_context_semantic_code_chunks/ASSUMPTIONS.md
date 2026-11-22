# Assumptions: Feature 002 (semantic code chunks)

Why this file exists: decisions in this feature rest on assumptions, some tested and some not. They are recorded here so an agent reading the code or the design can tell what was assumed, where it came from, and whether it has been verified. Evidence comes from `docs/design/verification.md`.

**Maintained by**: The reviewer only. **Last updated**: 2026-11-23

Status: ✅ Verified · 🟡 Partly verified · ❔ Unverified · 🔴 Invalidated or known to fail · ⚪ Owner decision. Test-host numbers (speed, memory) describe an old weak test laptop and are never production benchmarks.

| ID | Assumption | Status | Evidence and source | What would prove it wrong |
|---|---|---|---|---|
| A-001 | `jinaai/jina-embeddings-v2-base-code` (768 dimensions) at the pinned revisions is a suitable embedding for code search | 🟡 Partly verified | Fixture queries ranked the right file first (0.879, 0.820, 0.881) and the off-topic query scored 0.627. No labeled evaluation | A labeled relevance test |
| A-002 | Fixed 150-line windows are an adequate retrieval unit | ❔ Unverified | A chosen default. Retrieval quality of this size was not compared with other sizes | Comparing other window sizes on labeled queries |
| A-003 | Cutting text at 8000 characters rarely matters | 🟡 Partly verified (counts) | Cut by the 2048-token cap: 1 of 1,638 chunks on FastAPI, 0 of 2,600 on NestJS. Cuts by the 8000-character cap were not recorded on the public repositories. Effect on search quality not measured | Truncated chunks missing from relevant results |
| A-004 | The token cap (8192 by default; 2048 for the public eval) does not materially hurt retrieval | ❔ Unverified | Chosen to bound memory, since attention memory grows with the square of the token count. Uncapped runs were not measured on the public repositories. Layers built with different caps coexist, and cross-repository search mixes them | Quality difference between capped and uncapped layers |
| A-005 | Memory grows with the square of the token count, and a fresh embedder process every 100 chunks keeps it bounded | 🟡 Partly verified | Embedder peak RSS with the 2048-token cap: 1,849 MB on FastAPI, 1,606 MB on NestJS, 1,247 MB on the fixture. The growth law and the effect of the restarts were not measured on public repositories | A longer run showing growth across segments |
| A-006 | Vectors are reproducible across machines | ❔ Unverified | Not measured on public inputs, which is why the content hash excludes vectors | A different CPU producing different vectors |
| A-007 | Linking a chunk to entities by file plus start-line containment is sufficient | 🟡 Partly verified | Unit tests cover boundaries and malformed locations; 7,184 links on FastAPI and 9,581 on NestJS. Links were not hand-audited, and an entity is linked only to the chunk holding its start line | A hand audit finding misses |
| A-008 | A global vector index filtered to one snapshot, with a fetch of 600 and an exact-scan fallback, returns correct results | ✅ Verified (live tests) | Live test forces crowding and checks the fallback. The 600 figure is a chosen default. Exact-scan cost at the 20,000-chunk bound is untested | A repository near the chunk limit |
| A-009 | The weights and remote code can be baked into the image and run offline | ✅ Verified | Model loaded with no network after the `main` ref fix | An image rebuild changing revisions |
| A-010 | `transformers` must stay on 4.57.1 | 🟡 Partly verified | 4.57.1 works. The claim that the model's remote code breaks on 5.x comes from earlier analysis and was not re-tested here | n/a unless the pin is lifted |
| A-011 | A 35-minute lease renewed on every batch write protects against two builders | ✅ Verified | Live test refuses a second builder; the FastAPI (4,270 s) and NestJS (5,218 s) runs completed | A build stall longer than the lease |
| A-012 | Embedding speed on the test host (2.6 s per chunk on FastAPI, 2.0 s on NestJS) reflects only this machine | ⚪ Owner decision | Not a production figure | n/a (policy) |
