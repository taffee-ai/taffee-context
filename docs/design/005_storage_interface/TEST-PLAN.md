# 005 Storage interface: test plan

Run on the Ubuntu execution host, inside the base image, as for all other tests.

## Level 1: unit

- `ReadOnlyView` exposes only read methods. A write method call fails with `AttributeError`; the view holds no reference to the provider's write methods.
- Snapshot resolution rules with a fake store: newest ready by commit timestamp, tie by SHA, prefix matching exactly one, prefix matching none, prefix matching several.
- Error mapping: `NotFound` and `Ambiguous` produce the exact `ValueError` text the tools use today.
- Provider selection (existing tests).

## Level 2: provider contract (Neo4j)

Run against the throwaway database with a seeded fixture. The fixture is written with the Python write path (`stage_snapshot`, `publish_snapshot`) and, for chunks, with a test-only Cypher seeder (semantic writes are not yet in Python).

- Every read method returns the expected rows for the fixture.
- Staged snapshots are invisible to every read method.
- Reads are scoped: a second repo or commit never appears in results.
- Ordering matches the current queries (`ORDER BY` clauses are copied).

## Level 3: MCP parity (golden set)

- Capture: `golden-before/` (already captured, 13 outputs, byte-stable).
- After the change: rebuild the MCP image, redeploy the stack, run the same 13 calls, compare bytes with `cmp`.
- Pass: all 13 identical. Any difference is a failure unless recorded in DECISIONS.

## Level 4: stack lifecycle

- Kill all three services (SIGKILL), restart the stack, run Level 3 again. Data and job state must survive.
- Repeat the full cycle twice.

## Level 5: existing suites

- Full TypeScript suite unchanged (41 tests) and Python suites (storage, factory) pass.
