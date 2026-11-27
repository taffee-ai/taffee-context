# Semantic Code Chunks: User Guide

**Purpose**: Understand what semantic chunks are, how to use them, and what to do when ingestion is incomplete.

---

## What is a Semantic Chunk?

A **semantic chunk** is a fixed-size window of code (approximately 150 lines, max 8,000 characters) that represents a coherent logical unit. Each chunk is:

1. **Embedded**: Converted to a 768-dimensional vector using Jina model (jinaai/jina-embeddings-v2-base-code)
2. **Indexed**: Stored in Neo4j's vector index for fast semantic search
3. **Linked**: Connected to AST entities (classes, functions) it describes via `DESCRIBES` edges
4. **Immutable**: Tied to a specific commit and semantic config (model revision, token cap)

**Example**: In a 2,000-line TypeScript service, the code might be split into ~15–20 chunks, each capturing a cohesive piece of functionality (e.g., authentication middleware, database layer, API handlers).

---

## How Semantic Search Works

### Query Flow

```
User Query: "How is widget access validated?"
    ↓
Embed Query (Jina model, ~40ms)
    ↓
Vector Cosine Search in Neo4j (~30ms)
    ↓
Get Top 50 Chunks + their linked Entities
    ↓
Hybrid Score (0.50·VectorSim + 0.35·Degree + 0.15·Lexical)
    ↓
Return Top K Chunks with Code Evidence
```

### What Gets Indexed?

- Code snippets (function bodies, class definitions, logical blocks)
- Entity names and types (class, function, interface)
- Comments and docstrings (if parsed)
- NOT: minified code, generated code, test files

### Typical Results

For a query like **"session validation"**, you might get:

| Chunk | File | Lines | Relevance | Entity |
|-------|------|-------|-----------|--------|
| 1 | src/auth/session.guard.ts | 15–45 | 0.92 | `SessionGuard` class |
| 2 | src/middleware/auth.ts | 120–150 | 0.87 | `validateToken` function |
| 3 | src/entities/user.ts | 200–220 | 0.71 | `User` interface |

---

## Using Semantic Search via CLI

### Basic Search

```bash
taffee-mcp search "session validation" -r demo-shop --top 5
```

**Output** (table format by default):

```
File                    Score   Location
────────────────────────────────────────────────────
src/auth/session.guard.ts   0.92    lines 15–45
src/middleware/auth.ts  0.87    lines 120–150
src/entities/user.ts    0.71    lines 200–220
```

### JSON Output (for Agents)

```bash
taffee-mcp search "session validation" -r demo-shop --json
```

Returns structured JSON with full code snippets, line ranges, and confidence scores.

### Search Without Repo Filter

To search across **all ingested repos** (slow, use sparingly):

```bash
taffee-mcp search "database connection pool" --top 3
```

This finds relevant code in any repository.

---

## Semantic Layer States

After ingestion, a repository can be in one of four states:

| State | Meaning | What You Can Do |
|-------|---------|-----------------|
| `ready` | ✅ Full semantic layer available | Use vector search, full MCP-Turbo |
| `building` | 🔄 Ingestion in progress | Structural search only (AST + code) |
| `failed` | ❌ Ingestion failed (see logs) | Structural search only; retry ingestion |
| `null` | ⚠️ No semantic layer yet | Structural search only (very slow) |

### How to Check State

```bash
taffee-mcp stats -r demo-web
```

Look for `semanticLayerState` in the response. If it's not `ready`, semantic search won't work for that repo.

### What to Do If `building` or `null`

1. Check ingestion logs: `docker logs taffee-embed-worker` (on the host running the ingestion service)
2. Wait for completion (typically 5–30 minutes for 2K-node repos)
3. Verify ingestion: `taffee-mcp stats -r repo-name`
4. If stuck, contact the operator

---

## Understanding Chunk Windows

Chunks are created using a **150-line sliding window** with smart boundaries:

- **Start**: Beginning of file or after previous chunk
- **Size**: Try to fit ~150 lines
- **End**: Stop at logical boundary (end of class, function, or end-of-file)
- **Cap**: Never exceed 8,000 characters (about 2,000 tokens)

### Example: TypeScript Service

File: `src/services/OrderService.ts` (300 lines total)

```
Chunk 1: Lines 1–80     (imports, decorators, class definition start)
Chunk 2: Lines 80–160   (processPayment + helper methods)
Chunk 3: Lines 160–300  (error handling, cleanup, class end)
```

Each chunk is embedded independently, so queries like "place order" will hit Chunk 2 directly.

### What Happens If a Function Spans Chunks?

The function definition will be in one chunk, and its implementation might span into the next. During retrieval, if you ask about that function, you'll get both chunks (via the DESCRIBES relationship).

---

## Truncation: When Chunks Are Cut

If a single chunk exceeds the 8,000-character cap (rare, usually only for very large functions), TAFFEE truncates it and flags it:

```json
{
  "chunkId": "chunk-xyz",
  "file": "src/big-file.ts",
  "startLine": 100,
  "endLine": 280,
  "content": "[TRUNCATED: 8245 chars → 8000 chars]...",
  "truncated": true,
  "charactersTruncated": 245
}
```

**What This Means**: The code shown is cut short. For the full function, use `taffee-mcp code`.

---

## Performance: What to Expect

### Latency

| Operation | Time | Notes |
|-----------|------|-------|
| Search a 2K-node repo | ~80 ms | Vector index + AST expansion |
| Get top 10 results | +50 ms | Depends on result ranking |
| Fetch code lines | +35 ms | Via git blob |
| **Total** | **~165 ms** | Sub-second, ready for agent loops |

### Accuracy

Semantic search in TAFFEE:

- **Finds**: Function implementations, API handlers, middleware, utilities (things with substantial code)
- **Misses**: Configuration, constants, simple wrappers, dynamically dispatched code
- **Rank Stability**: Same query returns same top-5 results (deterministic, no LLM sampling)

### Recall (Completeness)

For a typical query like "how is authentication handled":

- Structural search (AST + grep): 60–75% recall (misses indirect flows)
- Semantic search (vectors + AST): 90–95% recall (finds related implementations)
- MCP-Turbo (vectors + degree + transitive): 96–98% recall (includes call chains)

---

## Troubleshooting

### "My search returned no results"

**Check**:
1. Is the semantic layer `ready`? `taffee-mcp stats -r repo`
2. Try a simpler query: `search "class" -r repo --top 1`
3. Try structural search as fallback: `taffee-mcp query "your topic" -r repo`

**Solution**:
- If layer is `building`, wait for completion
- If layer is `failed`, contact operator to retry ingestion
- If layer is `ready`, your query might be too specific; try shorter keywords

### "Results are not relevant"

**Possible causes**:
1. Query is too specific (model hasn't seen that exact phrasing in training)
2. Code uses domain-specific jargon not in embeddings
3. Function name is misleading compared to implementation

**Solution**:
- Rephrase query: "how is auth handled" instead of "session refresh token revocation"
- Use structural search `node ClassName` to inspect specific symbols
- Use `neighbors` to see callers/callees (AST-based, always accurate)

### "Chunks are missing from results"

**Possible causes**:
1. Chunk exists but has low relevance score
2. Chunk is in a different repository
3. Chunk wasn't ingested (semantic layer incomplete)

**Solution**:
```bash
# Increase result limit
taffee-mcp search "query" -r repo --top 20

# Check if chunk is in a different repo
taffee-mcp search "query" --top 5  # No -r filter

# Verify semantic layer
taffee-mcp stats -r repo
```

---

## Advanced: Semantic Search with MCP-Turbo

For AI agents, the recommended way to use semantic search is via `assemble_context_pack`:

```json
{
  "method": "assemble_context_pack",
  "params": {
    "repo": "demo-shop",
    "task": "Trace how user permissions are checked before an admin endpoint is called",
    "max_tokens": 4000
  }
}
```

This returns a **Trusted Context Pack** that combines:
- Top semantic chunks (vector search)
- Architectural anchors (important entities)
- Dependency chain (call graph)
- Code evidence (exact committed lines)
- Token budget (never exceeds 4000)

**Benefit**: One tool call instead of 4–6 sequential calls. Latency: <250ms.

---

## Semantic Config: What's Immutable

Once a repo is ingested with a semantic layer, the following cannot be changed without **rebuilding the entire layer**:

| Config | Value | Why It Matters |
|--------|-------|-----------------|
| Chunk size | 150 lines | Changes chunk boundaries → different vectors |
| Chunk cap | 8,000 chars | Larger cap = different truncation behavior |
| Model | jinaai/jina-embeddings-v2-base-code | Different model = different vectors |
| Model revision | 516f4baf... | Model updates change vectors |
| Token budget | 8192 (default) | Affects embedding process |

If you need to change any of these, the operator must:
1. Mark the snapshot as needing rebuild
2. Re-chunk the repo with new config
3. Re-embed all chunks
4. Re-index in Neo4j

This is intentional: **immutability prevents silent vector drift** and ensures that the same code always produces the same embeddings.

---

## Data Privacy & Security

Semantic chunks are:
- ✅ Stored in Neo4j (on-premise, no cloud)
- ✅ Derived from committed code only (not local working tree)
- ✅ Pinned to a specific commit (reproducible)
- ✅ Access-controlled via MCP Bearer tokens
- ❌ NOT sent to Hugging Face (model loaded locally once)
- ❌ NOT cached in vector stores other than Neo4j

All query logs are retained for audit purposes and include: caller token, query text, repo, results returned, latency, timestamp.

---

## See Also

- [Structural Context Guide](structural-context.md) — AST entities and relationships
- [MCP Server Guide](../../context/serving/mcp/README.md) — all tools and authentication
- [Operator Guide](operator-guide.md) — how to ingest and manage ingestion
- [Verification Results](../design/verification.md) — test coverage and known limitations
