# 005 Storage interface: decisions

- **D-005-1 Reads run in Python, in-process.** The MCP server is Python and so is the storage layer, so no network hop is added. Ingestion stays in TypeScript for now and writes through its own code.
- **D-005-2 The MCP server gets a read-only view.** Read-only is enforced by the object it holds, not by convention. The provider's database user is read-only as well (required before production).
- **D-005-3 Acceptance is byte parity.** The golden set captured before the change must match exactly after it. Any intended change to output must be recorded here first.
- **D-005-4 Each provider documents a read-only database user.** Neo4j's read-only role is not implemented yet; it is an open item in IMPLEMENTATION.md, not a silent gap.
- **D-005-5 Tool interface is frozen.** Names, parameters, text and errors do not change in this step.
- **D-005-6 The pack moves in phase 2.** It has more methods and its own behaviour to protect; it is not mixed into phase 1.

- **D-005-7 Read-only is enforced in three layers, and the last one is open.**
  1. *Code:* the MCP server holds only `ReadOnlyView`, which has no write methods.
  2. *Server:* every read runs as a read-only transaction, and Neo4j refuses a write inside it, even if the query contains `CREATE`. Tested: `test_read_enforcement`.
  3. *Credential:* the MCP service still holds the Neo4j admin password, so anyone with that container's environment can write directly. Neo4j Community has no roles, and a second user gets full write access (tested and removed on 2026-10-15). A low-privilege credential needs Neo4j Enterprise, or a provider whose access control supports read-only users. Open.
