# Test Plan: MCP-Turbo Context Pack Engine

## Scope
Test the end-to-end `assemble_context_pack` pipeline across unit, integration, and live MCP test suites.

## Test Strategy

1. **Unit Testing (Offline / No DB)**:
   * **Knapsack Packer**: Test token budgeting logic with simulated chunk sizes; assert output never exceeds `max_tokens`.
   * **Hybrid Ranker**: Validate score weighting ($\alpha=0.50, \beta=0.35, \gamma=0.15$) on mocked vector similarities and degree centralities.
   * **Parameter Validation**: Validate handling of missing `repo`, invalid `commit` SHAs, and out-of-range `max_tokens`.

2. **Integration Testing (Live Neo4j & FastMCP)**:
   * **Single-Pass Cypher Query**: Run live Cypher query against a test Neo4j snapshot; verify returned record structure.
   * **Containment Verification**: Assert that returned code chunks accurately correspond to the AST entities via `DESCRIBES` relationships.
   * **Commit Isolation**: Query two snapshots of the same repo; assert zero entity leakage between different commits.

3. **Performance & Latency Gates**:
   * Measure wall-clock execution time of `assemble_context_pack` on the 3-function fixture and on a public repository.
   * Pass gate: Latency must stay under **1000 ms** on the test host.

4. **Security & Redaction**:
   * Verify that bearer tokens are required (401 on unauthorized).
   * Verify path confinement: requests cannot read files outside the repository checkout.

5. **Validator Verification Suite (~15 Benchmark Repositories)**:
   * **Objective**: Quantitatively validate the Laya JEV validator (detecting true positives vs rubber-stamping false positives).
   * **Dataset Scale**: ~15 well-known repositories across diverse architectural categories (Web frameworks, CLI tools, async/distributed systems, ORMs, and monorepos).
   * **Protocol**: Evaluate on pinned commit SHAs with real GitHub issue descriptions and golden maintenance patches.
   * **Target Metrics**: Validator precision ≥ 90%, false-positive rubber-stamp rate ≤ 3%, expected calibration error (ECE) ≤ 0.08.
