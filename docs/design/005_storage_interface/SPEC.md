# 005 Storage interface: overview

This folder holds the design for a storage layer that lets Context run on more than one graph database, and gives the MCP server a read-only way to reach the data.

Read in this order:

1. [REQUIREMENTS.md](REQUIREMENTS.md): what must be true.
2. [DESIGN.md](DESIGN.md): the layers, the read contract, and the read-only view.
3. [DECISIONS.md](DECISIONS.md): the choices made, and why.
4. [TEST-PLAN.md](TEST-PLAN.md): how each requirement is checked.
5. [IMPLEMENTATION.md](IMPLEMENTATION.md): status, and the source lines each read replaces.

The write side of the contract (stage and publish) is implemented and tested in `python/`. The read side is the subject of this change.
