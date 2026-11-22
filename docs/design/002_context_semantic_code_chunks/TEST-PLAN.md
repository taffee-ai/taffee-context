# Test plan: semantic code chunks

Follow the execution policy for the active repository: nothing builds or tests on the editing Mac; everything runs in containers on the designated test host (see `_ground-truth/BUILD_AND_TEST.md`, kept outside this repository).

## Host rules that apply to this feature

- The host has about 5.8 GB RAM and almost no free swap. Loading the model once froze it for about 20 minutes.
- Run **one model-loading container at a time**. Check `free -m` and `uptime` before each model run and stop if load climbs.
- Run model containers with `--memory` equal to `--memory-swap` (for example 2.4 GB) so an overrun kills the container instead of swapping the host.
- Use `nohup` or a background task for anything over about 30 seconds and tail a log; do not poll in a tight loop.
- Stopping other containers to free memory or ports is allowed only with permission: list them first, use `docker stop` (never `rm`), never touch volumes, and report which ones were stopped.
- Live tests run one file at a time (`--test-concurrency=1`, already in `package.json`) because the test Neo4j has one CPU.

## Levels, in order

| Level | Command | Needs | Pass criteria |
|---|---|---|---|
| 1. Typecheck | `npm run typecheck` | Node 20 image | 0 errors |
| 2. Unit tests | `npm test` | Node 20 image | all unit tests pass; live tests reported as skipped |
| 3. Live tests | `TAFFEE_NEO4J_TEST=1 npm test` (with `NEO4J_URI`, `NEO4J_PASSWORD`, `--network host`) | Neo4j 5.26, test image | 28 of 28 pass, 0 skipped (4 structural unit, 2 structural live, 15 chunk unit, 7 semantic live) |
| 4. Fixture with the real model | `ingest`, `chunk-embed`, `chunk-embed` again, `search` on-topic and off-topic | Embedder image, Neo4j | first run `ready`, repeat `unchanged`, right file ranks first, off-topic scores clearly lower |
| 5. One real repository | `chunk-embed` in the background with a log, then `search` | as above, time budget of tens of minutes | status `ready`; chunk, truncated and link counts recorded |
| 6. Failure injection | kill or time out the embedder mid-run, then rerun; start a second `chunk-embed` during a run | as above | partial run not searchable and has no links; rerun embeds only the missing chunks; second launch refused |
| 7. Memory check | run the heaviest-chunk repo under a no-swap container limit with a token cap | as above | container not OOM-killed; peak recorded |

## What to record for every host run

Commands, image tags and versions (Node, Python, torch, transformers, Neo4j), pass and fail counts, chunk / truncated / token-truncated / link counts, model load and embedding seconds, peak resident memory (the embedder's own report and the container peak), host load and available memory before and after, and anything left unverified. Put results in `docs/design/verification.md` and summarize in this folder's VERIFICATION.md. Never write a pass that was not seen in the output.

## Regression triggers

Re-run levels 1 to 3 after any change to: the chunk window or cap constants, `semanticConfigHash` or `semanticContentHash`, the pinned model or code revision, the `transformers` version, the schema V2 statements, or the search query. Re-run level 4 after any change to the embedder script or the image.

## Exit criteria for this feature

All of REQUIREMENTS.md items 1 to 8 have a passing test or a recorded host run (see TEST-CASES.md sections A to C), and the items in TEST-CASES.md section D are listed as unverified in VERIFICATION.md rather than implied to work.
