# Test cases: semantic code chunks

Three layers: unit tests (no database, no model), live tests (real Neo4j, deterministic fake embedder so the real loader, vector index and search run without the model), and host runs (real model on the test host). Test names below are the actual names in the test files.

## A. Unit tests: `context/testing/context-chunks.test.ts` (15)

| # | Test | What it proves |
|---|---|---|
| U1 | chunk windows: boundaries, trailing newline, line numbers | Windows are 150 lines, numbered from 1, a trailing newline adds no empty window |
| U2 | whitespace-only windows are skipped without renumbering later windows | Skipped windows do not shift the line numbers (and so the ids) of later ones |
| U3 | only configured source files are chunked | Extension filter, `.min.` files and `node_modules` are excluded by `chunkSource` itself |
| U4 | long chunks are cut and flagged, never split in a surrogate pair | 8000-character cap, `truncated` flag, counts, no broken emoji or astral characters |
| U5 | chunk count bound is enforced and chunk ids have the documented shape | 20,000-chunk limit; id is `<snapshot>::chunk::<file>::<startLine>` |
| U6 | semantic start decision: complete layers are immutable, incomplete ones may restart under a new config | `new`, `resume`, `unchanged`, `restart`, and the two immutable-conflict errors |
| U7 | token cap: default keeps the pre-cap hash, a lower cap changes it, env is validated | Existing snapshots stay valid; `EMBED_MAX_TOKENS` accepts only 128 to 8192 |
| U8 | content hash depends on layout and links but not chunk order or text | Hash is stable under reordering and ignores vectors and text |
| U9 | links: inside, boundaries, other file, malformed locations | Entity start line inside the range links; first and last line included; other files and bad `L<n>` ignored |
| U10 | embedding validation rejects wrong dimension, non-finite numbers and malformed rows | Dimension 768, finite values, token fields well-formed |
| U11 | embedding file: count mismatch, unknown and duplicate ids, partial last line | Output file is validated row by row; a cut-off last line is tolerated only when allowed |
| U12 | search validation bounds topK and query and rejects unknown arguments | topK 1 to 25, query length, allowed keys only |
| U13 | the image bakes the same pinned revisions the code uses, and the embedder runs offline | `Dockerfile.base` revisions equal `SEMANTIC_CONFIG`; offline flags present |
| U14 | incremental reader hands over rows as lines complete and keeps a half-written line for later | Rows can be saved while the model is still writing |
| U15 | embedder runner saves rows while the process runs and keeps completed rows when it fails | Failure after some rows leaves those rows delivered |

## B. Live tests: `context/testing/context-semantic-neo4j.test.ts` (7, fake embedder, require `TAFFEE_NEO4J_TEST=1`)

| # | Test | What it proves |
|---|---|---|
| L1 | idempotent re-run, links, stored config and search | Second run is `unchanged` and embeds nothing; links and config are stored; search returns the expected file |
| L2 | interrupted run is not searchable, leaves no links, and resumes only the missing chunks | A failed run stays `building`, has no `DESCRIBES` links, and the resume embeds only the chunks without vectors |
| L3 | an incomplete layer restarts under a new token cap and records token truncation; a complete one is immutable | `restart` deletes chunks and rebuilds; token-truncated count is stored; a ready layer refuses the change |
| L4 | a concurrent builder is refused while the lease is held | Second builder gets "already in progress"; no second embed |
| L5 | no leakage across repositories or commits, and underfill is reported | Results never include another repo's or commit's chunks; `filteredOut` and `possiblyIncomplete` are honest |
| L6 | falls back to an exact scan when other snapshots crowd the global index | `method: exact-scan` returns the snapshot's true top results when 600 foreign vectors fill the index fetch |
| L7 | config change on a complete snapshot is refused, and a structural snapshot is required | Chunk size, model revision and character cap changes are refused; `chunk-embed` without a ready structural snapshot fails |

## C. Host runs with the real model (manual, recorded in `docs/design/verification.md`)

| # | Case | Expected | Observed |
|---|---|---|---|
| H1 | Fixture of 3 Python files: `chunk-embed` | 3 chunks, links created, status `ready` | 3 chunks, 0 truncated, 11 links |
| H2 | Repeat `chunk-embed` | `unchanged`, no model load | `unchanged`, 4 s wall |
| H3 | Fixture search, on-topic queries | Right file first | payments, auth and csv queries each ranked the right file first (0.879, 0.820, 0.881) |
| H4 | Fixture search, off-topic query | Low scores | "database connection pool" topped out at 0.627 |
| H5 | Public repo FastAPI at `913c68062c89` | Chunks embedded, layer ready | 1,638 chunks, 1 cut by the 2048-token cap, 7,184 links, `ready` |
| H7 | Second launch while a build holds the lease | Refused, no second model load | Refused ("Semantic build already in progress") |
| H8 | Offline run | Model loads with no Hugging Face access | Loaded after the `main` ref fix in `prefetch_model.py` |
| H10 | Public repo NestJS at `2731c18054fb` | Layer `ready` | 2,600 chunks, 0 cut, 9,581 links, `ready` |

## D. Not covered by any test (do not assume these work)

- Submodule refusal and symlink refusal in `collectSource` (the symlink check is shared code covered by the 001 live test, but not exercised through `chunk-embed`).
- The 5000-file, 1 MiB-per-file, 256 MiB-output and 120 s collect bounds.
- Search quality against labeled data (only the fixture queries were judged by reading results).
- Behaviour on a different CPU type or a different `transformers` version (pinned at 4.57.1 on purpose).
- The cause of the earlier host freeze (a hypothesis only).
- Search across snapshots built with different token caps.
