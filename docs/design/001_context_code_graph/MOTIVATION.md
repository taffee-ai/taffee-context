# Motivation

AI agents need durable context about codebases that is cheaper, faster, and more
precise than repeatedly scanning raw files. The workbench proved a first version:
Graphify extracts a code graph, Neo4j stores immutable snapshots, and retrieval
queries can answer repo/version-scoped questions.

This feature extracts that working capability into `taffee-context` as the first
clean reusable component.
