"""The read-only view the MCP server holds. It exposes read operations only.

Methods are delegated explicitly (no __getattr__), so a write operation or the raw driver cannot be reached through it.
"""
from __future__ import annotations

from typing import Any

from .contract import GraphStore


class ReadOnlyView:
    """Read-only view of a store. The MCP service holds only this object."""
    def __init__(self, store: GraphStore) -> None:
        """Wrap a store. The view keeps no other reference to it."""
        self._store = store

    def list_repos_page(self, query: str, limit: int, offset: int, all_commits: bool) -> tuple[int, list[dict[str, Any]]]:
        """Delegates to the store; see ReadStore.list_repos_page."""
        return self._store.list_repos_page(query, limit, offset, all_commits)

    def resolve_snapshot(self, repo_id: str, commit_prefix: str | None = None) -> str:
        """Delegates to the store; see ReadStore.resolve_snapshot."""
        return self._store.resolve_snapshot(repo_id, commit_prefix)

    def stats(self, repo_id: str, commit_sha: str) -> dict[str, Any]:
        """Delegates to the store; see ReadStore.stats."""
        return self._store.stats(repo_id, commit_sha)

    def find_nodes(self, repo_id: str, commit_sha: str, label: str) -> list[dict[str, Any]]:
        """Delegates to the store; see ReadStore.find_nodes."""
        return self._store.find_nodes(repo_id, commit_sha, label)

    def neighbours(self, repo_id: str, commit_sha: str, node_id: str, relation: str | None, limit: int) -> list[dict[str, Any]]:
        """Delegates to the store; see ReadStore.neighbours."""
        return self._store.neighbours(repo_id, commit_sha, node_id, relation, limit)

    def read_graph(self, repo_id: str, commit_sha: str) -> dict[str, list[dict[str, Any]]]:
        """Delegates to the store; see ReadStore.read_graph."""
        return self._store.read_graph(repo_id, commit_sha)

    def community_members(self, repo_id: str, commit_sha: str, community_id: str, limit: int) -> list[dict[str, Any]]:
        """Delegates to the store; see ReadStore.community_members."""
        return self._store.community_members(repo_id, commit_sha, community_id, limit)

    def shortest_path(self, repo_id: str, commit_sha: str, source_id: str, target_id: str, hops: int,
                      undirected: bool) -> list[dict[str, Any]]:
        """Delegates to the store; see ReadStore.shortest_path."""
        return self._store.shortest_path(repo_id, commit_sha, source_id, target_id, hops, undirected)

    def semantic_state(self, repo_id: str, commit_sha: str) -> str:
        """Delegates to the store; see ReadStore.semantic_state."""
        return self._store.semantic_state(repo_id, commit_sha)

    def scoped_chunks(self, snapshot: str, vector: list[float], top_k: int) -> list[dict[str, Any]]:
        """Delegates to the store; see ReadStore.scoped_chunks."""
        return self._store.scoped_chunks(snapshot, vector, top_k)

    def global_chunks(self, vector: list[float], top_k: int) -> list[dict[str, Any]]:
        """Delegates to the store; see ReadStore.global_chunks."""
        return self._store.global_chunks(vector, top_k)

    def chunk_symbols(self, snapshot: str, chunk_id: str) -> list[str]:
        """Delegates to the store; see ReadStore.chunk_symbols."""
        return self._store.chunk_symbols(snapshot, chunk_id)

    def file_has_entities(self, snapshot: str, file: str) -> bool:
        """Delegates to the store; see ReadStore.file_has_entities."""
        return self._store.file_has_entities(snapshot, file)

    def close(self) -> None:
        """Close the underlying store."""
        self._store.close()
