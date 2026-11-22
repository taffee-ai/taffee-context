"""Storage providers. Select one by name; each provider implements the GraphStore contract (contract.py)."""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from .contract import Ambiguous, GraphStore, NotFound
from .read_view import ReadOnlyView


def _neo4j(env: Mapping[str, str], read_timeout: float) -> GraphStore:
    """Build the Neo4j store from NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD and NEO4J_DATABASE."""
    from .neo4j_store import Neo4jStore

    return Neo4jStore.connect(env["NEO4J_URI"], env.get("NEO4J_USER", "neo4j"), env["NEO4J_PASSWORD"],
                              env.get("NEO4J_DATABASE", "neo4j"), read_timeout=read_timeout)


# Providers are added here. A new database is one entry, plus its implementation and the contract tests.
PROVIDERS: dict[str, Callable[[Mapping[str, str], float], GraphStore]] = {
    "neo4j": _neo4j,
}


def _provider_name(provider: str | None, env: Mapping[str, str]) -> str:
    """Return the provider name from the argument or GRAPH_DB_PROVIDER; raise ValueError if unknown."""
    name = (provider or env.get("GRAPH_DB_PROVIDER", "neo4j")).strip().lower()
    if name not in PROVIDERS:
        raise ValueError(f"unknown graph database provider '{name}'; supported: {', '.join(sorted(PROVIDERS))}")
    return name


def open_store(provider: str | None = None, env: Mapping[str, str] | None = None) -> GraphStore:
    """Full store (reads and writes). Used by ingestion and by tests; the MCP server uses open_read_store."""
    env = os.environ if env is None else env
    return PROVIDERS[_provider_name(provider, env)](env, float(env.get("QUERY_TIMEOUT_SECONDS", "15")))


def open_read_store(env: Mapping[str, str] | None = None) -> ReadOnlyView:
    """Read-only view for the MCP server: the only storage object the server holds."""
    env = os.environ if env is None else env
    return ReadOnlyView(open_store(env=env))


__all__ = ["Ambiguous", "NotFound", "ReadOnlyView", "open_read_store", "open_store", "PROVIDERS"]
