# Structural Code Context: User Guide

**Purpose**: Understand the AST (Abstract Syntax Tree), entity types, relationships, and how to query the code graph.

---

## What is Structural Context?

Structural context is the **code graph**: entities (classes, functions, interfaces) and their relationships (calls, imports, extends, contains) extracted via tree-sitter, stored in Neo4j, and queryable via MCP.

It answers questions like:
- **What is a symbol?** Name, type, file location, line range
- **Who calls this function?** Direct callers and chains of calls
- **What does this class import?** Dependencies and their sources
- **What is affected if I change this?** Impact analysis via transitive closure

---

## Entity Types

Each symbol in the code is a `ContextEntity` with a type:

| Type | Examples | Typical Properties |
|------|----------|-------------------|
| `class` | User, OrderService, AuthGuard | name, file, startLine, endLine, extends, implements |
| `function` | processPayment, validateToken, handleRequest | name, file, startLine, endLine, returns |
| `interface` | UserRepository, Logger, Config | name, file, startLine, endLine, properties |
| `type` | Enum, Union, TypeAlias | name, file, startLine, endLine |
| `variable` | constant, exported config | name, file, startLine, endLine |
| `method` | constructor, processPayment (inside a class) | name, file, startLine, endLine, parent class |
| `file` | src/services/payment.ts | name, path, lineCount |
| `module` | node_modules/express | name, version |

**Note**: Not all languages parse all types equally. JavaScript/TypeScript are most complete; Python and Java support 80–90% of types.

### Inspecting an Entity

```bash
taffee-mcp node OrderService -r demo-shop
```

**Output**:
```json
{
  "label": "OrderService",
  "type": "class",
  "file": "src/services/OrderService.ts",
  "startLine": 12,
  "endLine": 145,
  "degree": 34,
  "community": 3,
  "connections": 34
}
```

**What This Means**:
- `degree: 34` → This class is referenced 34 times (called, imported, extended)
- `community: 3` → Part of community cluster 3 (related classes grouped together)
- `connections: 34` → 34 entities connect to it

---

## Relationship Types

Entities are connected via `RELATES` edges, each with a `relation` property:

| Relation | Meaning | Example | Direction |
|----------|---------|---------|-----------|
| `calls` | Function A calls Function B | `OrderService.place()` → `Logger.log()` | A → B |
| `imports` | File/Module imports another | `payment.ts` imports `Logger` | A → B |
| `imports_from` | Specific import path | `from "express"` | A → B |
| `extends` | Class/Interface inheritance | `AdminGuard extends CanActivate` | A → B |
| `implements` | Class implements interface | `CustomerService implements ICustomerRepo` | A → B |
| `contains` | File/Module contains entity | `auth.ts` contains `AuthGuard` | A → B |
| `references` | General reference | Variable assigned to function | A → B |
| `indirect_call` | Runtime dispatch (harder to track) | `obj[method]()` or `router[verb]()` | A → B |

### Relationship Confidence

Relationships have a `confidence` score [0, 1]:

- `0.99` → Tree-sitter found explicit reference (highest confidence)
- `0.85` → Heuristic match (e.g., string-based dependency injection)
- `0.50` → Inferred relationship (conservative guess)

**Use in Queries**: When doing impact analysis, prefer high-confidence edges.

---

## Common Queries

### "Where is a symbol defined?"

```bash
taffee-mcp node CustomerService -r demo-shop
```

Returns: file, line range, type, what it imports/calls.

### "What calls this function?"

```bash
taffee-mcp neighbors CustomerService -r demo-shop --relation calls
```

This shows **direct callers only** (1 hop). For transitive (2+ hops):

```bash
taffee-mcp affected CustomerService -r demo-shop --depth 2 --relation calls
```

### "What does this class import?"

```bash
taffee-mcp neighbors OrderService -r demo-shop --relation imports_from
```

### "Who inherits from this interface?"

```bash
taffee-mcp neighbors ICustomerRepository -r demo-shop --relation extends
```

### "What's the call chain from A to B?"

```bash
taffee-mcp path OrderService Logger -r demo-shop
```

Returns: shortest chain of relationships (could be multi-hop or multi-relation).

### "What's the impact of changing this class?"

```bash
taffee-mcp affected OrderService -r demo-shop --depth 3
```

Returns: everything that (transitively) calls or imports this class.

---

## Navigation Patterns

### Pattern 1: Start with a File

```bash
# Find all entities in a file
taffee-mcp query "OrderService" -r demo-shop --mode dfs
# Returns: functions, classes, and methods in that file + their relationships
```

### Pattern 2: Start with a Symbol Name

```bash
# Find all definitions named "process*"
taffee-mcp node "process" -r demo-shop  # Exact match
# For partial matches, use structural search:
taffee-mcp query "place order" -r demo-shop
```

### Pattern 3: Follow a Call Chain

```bash
# Get direct neighbors
taffee-mcp neighbors Controller -r demo-shop
# ↓
# Pick an interesting caller, traverse further
taffee-mcp neighbors Middleware -r demo-shop
# ↓
# Use path-finding for the full chain
taffee-mcp path RequestHandler Middleware -r demo-shop
```

### Pattern 4: Impact Analysis

```bash
# What breaks if I delete this function?
taffee-mcp affected "deleteCustomer" -r demo-shop --depth 2

# What breaks if I change this interface?
taffee-mcp affected "ICustomerRepository" -r demo-shop --depth 3 --relation implements
```

---

## Understanding Graph Statistics

```bash
taffee-mcp stats -r demo-shop
```

**Output Example**:
```json
{
  "nodes": 1167,
  "edges": 2377,
  "communities": 12,
  "avgDegree": 4.08,
  "maxDegree": 87,
  "chunks": 140
}
```

**Interpretation**:
- `nodes: 1167` → 1,167 entities (classes, functions, etc.)
- `edges: 2377` → 2,377 relationships (calls, imports, etc.)
- `communities: 12` → Entities naturally cluster into 12 groups (related classes)
- `maxDegree: 87` → The most-connected entity has 87 inbound/outbound edges (e.g., Logger, Express)
- `chunks: 140` → Repository was split into 140 semantic chunks for embedding

**What High Degree Means**: An entity with degree 87 is a **hub**. It's either:
- A widely-used utility (Logger, Config)
- A major service (AuthService, Database)
- A middleware (error handling, logging)

These are good anchor points for understanding the system.

---

## Degree Centrality: Why It Matters

In a code graph, **degree** (number of connections) correlates with importance:

| Degree | Interpretation | Example |
|--------|-----------------|---------|
| 1–5 | Specific helper or leaf function | `calculateTax()`, `formatDate()` |
| 5–20 | Regular service or module | `EmailService`, `AuthService` |
| 20–50 | Core infrastructure | `Database`, `Logger`, `Config` |
| 50+ | Widely-reused utilities or frameworks | `Express`, `ORM`, `HTTP client` |

Use degree to:
- Find **hubs**: `taffee-mcp hubs -r repo --top 10` (most-connected entities)
- Prioritize testing: high-degree changes affect more code
- Guide onboarding: understand hubs first, then leaf functions

---

## Community Detection: Logical Grouping

TAFFEE runs community detection (Louvain algorithm) to group related entities:

```bash
taffee-mcp community 3 -r demo-shop
```

Returns: all entities in community 3 (e.g., all auth-related classes and functions).

**Use Cases**:
- **Understand architecture**: What's grouped together?
- **Refactoring guidance**: Move related entities to the same module
- **Dependency untangling**: Communities often represent logical boundaries

**How It Works**:
1. Entities are connected if they call/import/extend each other
2. Communities are groups that are internally densely connected
3. Edges between communities are fewer (clean boundaries)

---

## Dealing with Missing or Incomplete Data

### "This symbol doesn't appear in the graph"

**Possible reasons**:
1. Symbol is dynamically created (e.g., via metaprogramming)
2. Symbol is in a node_modules dependency
3. Symbol is in a file that wasn't committed yet

**Solution**:
- Check if it's in dependencies: `taffee-mcp node "express" -r repo`
- Verify the file is committed: `git ls-files | grep filename`
- Use semantic search as fallback: `taffee-mcp search "symbol description"`

### "I see a call edge, but I don't see it in the code"

**Possible reasons**:
1. Call is dynamic (string-based dispatch, reflection)
2. Call is through a base class or interface
3. Call confidence is low (heuristic match)

**Solution**:
- Check relationship confidence: look for `confidence: 0.5` (heuristic)
- Read the code: `taffee-mcp code <file> --from <line> --to <line>`
- Verify manually or skip if uncertain

### "The graph is outdated (I just added a file)"

Ingestion happens at a specific commit. New files in the working tree won't appear.

**Solution**:
- Commit your changes: `git add . && git commit`
- Ask operator to re-ingest the repo at the new commit
- Until then, queries will hit the old state

---

## Limitations of Structural Context

What the graph captures well:
- ✅ Direct function calls (same file or imported)
- ✅ Class inheritance and interface implementation
- ✅ Module dependencies (imports)
- ✅ Simple type references

What's hard or missing:
- ❌ Reflection-based calls (e.g., `obj[methodName]()`)
- ❌ Runtime dispatch in routing libraries
- ❌ Plugin systems (dynamically loaded code)
- ❌ Macros, templates, code generation
- ❌ Implicit dependencies (configuration files, environment variables)

**Workaround**: Use **semantic search** for cases where structural queries fail. Semantic search finds implementations by meaning, not just syntax.

---

## Performance

| Query | Latency | Notes |
|-------|---------|-------|
| `node` (entity lookup) | ~30 ms | Direct Neo4j index lookup |
| `neighbors` (1 hop) | ~50 ms | Small traversal |
| `affected` (2+ hops) | ~150 ms | Graph traversal, can be slow on hubs |
| `path` (shortest path) | ~80 ms | Neo4j pathfinding |
| `community` (fetch all members) | ~60 ms | Community lookup |
| `stats` (graph-wide) | ~100 ms | Full graph scan |

All queries should complete in <200ms on a 2000-node graph.

---

## Advanced: Direct Cypher Queries

For custom analysis, the operator can expose Cypher queries. Examples:

**Find all files that import AuthService**:
```cypher
MATCH (file:ContextEntity {type: 'file'})-[:CONTAINS]->(e:ContextEntity)
     -[:imports]->(auth:ContextEntity {label: 'AuthService'})
RETURN file.name, COUNT(e) as importCount
ORDER BY importCount DESC
```

**Find entities with high fan-in (many callers)**:
```cypher
MATCH (e:ContextEntity)<-[:calls]-(caller)
RETURN e.label, COUNT(caller) as incomingCalls
ORDER BY incomingCalls DESC
LIMIT 10
```

---

## See Also

- [Semantic Chunks Guide](semantic-chunks.md) — vector search and embeddings
- [MCP Server Guide](../../context/serving/mcp/README.md) — all tools and usage
- [Operator Guide](operator-guide.md) — ingestion and troubleshooting
- [Data Model](data-model.md) — Neo4j schema and properties
