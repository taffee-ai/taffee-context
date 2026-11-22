# Motivation: semantic code chunks

## The problem

The structural graph (feature 001) answers questions about things you can name: who calls `checkWidgetAccess`, what does this file import. It cannot answer the question people and agents actually start with: "where does this system validate widget access before an action?" The words in the question rarely match the identifiers in the code. Grep finds text, the graph finds names, and neither finds meaning.

Without a semantic layer an agent has to guess identifiers, grep, read whole files, and repeat. That costs round trips and tokens, and it misses code whose names do not contain the obvious words.

## What this feature adds

A search-by-meaning layer on top of an existing, immutable structural snapshot:

- The source of an exact commit is cut into 150-line windows.
- Each window is turned into a 768-number vector by a local code-embedding model.
- Vectors live in Neo4j beside the graph, with a cosine vector index.
- Each window is linked to the graph entities that start inside it, so a hit returns file, line range, score and the symbols it contains, and the caller can continue with graph queries (callers, callees, impact) from there.

## Constraints that shaped the design

| Constraint | Consequence |
|---|---|
| Code is sensitive; no source may leave the environment | Local model, offline at run time, no hosted API or key, weights baked into the image |
| Results must be reproducible and auditable | Model and remote-code revisions pinned to commit hashes; config and content hashes; a complete layer is immutable |
| The test host is a 4-thread laptop with about 5.8 GB RAM | Memory bounded by token cap, process segments and no-swap container limits; incremental saves so a failure loses seconds |
| Embedding takes tens of minutes per repository | Separate `chunk-embed` command with its own `building` and `ready` state; resumable; lease against two builders |
| Structural readiness and hashes must not change | Semantic state is a separate set of properties; the structural path is untouched |
| One shared vector index across all snapshots | Search always filters to one snapshot, reports what was filtered, and falls back to an exact scan when crowded out |

## What it is for

- Direct use: `search` finds code by meaning in one repository at one commit.
- As a building block: the MCP server's `semantic_search` tool exposes it to agents, and feature 003 (the single-shot context pack) uses chunk vectors as one of its ranking signals.

## What it does not do

No non-code sources, no permissions or token budgeting, no semantic search inside the model-callable `graph_query` tool (it needs its own latency and security design), and no stored chunk text (code is read from Git when needed). See REQUIREMENTS.md for the full out-of-scope list.
