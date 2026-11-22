"""Storage contract. Every graph database provider implements GraphStore; nothing outside storage imports a driver.

Invariants (docs/design/005_storage_interface/DESIGN.md): a published snapshot is immutable, staged data is never
read, every read is scoped to one snapshot, reads never write, and a snapshot becomes visible only at publish.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class NotFound(ValueError):
    """No ready snapshot matches the request. The message is the text the MCP tools return."""


class Ambiguous(ValueError):
    """More than one ready snapshot matches the request. The message is the text the MCP tools return."""


@dataclass(frozen=True)
class SnapshotRef:
    """Identifies one snapshot: a repository at one commit."""
    repo_id: str
    commit_sha: str


@dataclass(frozen=True)
class StructuralNode:
    """One code entity of a snapshot, as ingestion writes it."""
    local_id: str
    label: str
    kind: str
    source_file: str
    source_location: str
    community: str | None = None  # stored as text, as the TypeScript loader does
    native_order: int | None = None
    native_properties_json: str | None = None


@dataclass(frozen=True)
class StructuralEdge:
    """One relation between two entities of a snapshot."""
    source: str
    target: str
    relation: str
    confidence: str | None
    source_file: str
    source_location: str
    context: str | None = None
    native_order: int | None = None
    native_properties_json: str | None = None


@dataclass(frozen=True)
class SnapshotSummary:
    """Counts, hashes and state of a snapshot as stored."""
    snapshot_id: str
    ready: bool
    staged: bool
    content_hash: str | None
    artifact_hash: str | None
    declared_nodes: int
    declared_edges: int
    nodes: int
    edges: int
    semantic_status: str | None


@dataclass
class StageRequest:
    """Everything needed to stage one snapshot in a single call."""
    ref: SnapshotRef
    content_hash: str
    artifact_hash: str
    nodes: list[StructuralNode]
    edges: list[StructuralEdge]
    metadata: dict[str, Any] = field(default_factory=dict)


class ReadStore(Protocol):
    """Read operations. The MCP server holds only this surface (through ReadOnlyView)."""

    def list_repos_page(self, query: str, limit: int, offset: int, all_commits: bool) -> tuple[int, list[dict[str, Any]]]:
        """Ready repos, filtered by name, with the total count and one page of rows."""

    def resolve_snapshot(self, repo_id: str, commit_prefix: str | None = None) -> str:
        """The commit of the newest ready snapshot, or of the one matching the prefix. Raises NotFound or Ambiguous."""

    def stats(self, repo_id: str, commit_sha: str) -> dict[str, Any]:
        """Node, community, edge-confidence and chunk counts for one snapshot."""

    def find_nodes(self, repo_id: str, commit_sha: str, label: str) -> list[dict[str, Any]]:
        """Up to five entities matching a label: exact, then suffix, then substring."""

    def neighbours(self, repo_id: str, commit_sha: str, node_id: str, relation: str | None, limit: int) -> list[dict[str, Any]]:
        """Direct connections of one node, optionally limited to one relation."""

    def read_graph(self, repo_id: str, commit_sha: str) -> dict[str, list[dict[str, Any]]]:
        """Every node and edge of a snapshot, with their native properties."""

    def community_members(self, repo_id: str, commit_sha: str, community_id: str, limit: int) -> list[dict[str, Any]]:
        """Entities of one community, up to limit rows."""

    def shortest_path(self, repo_id: str, commit_sha: str, source_id: str, target_id: str, hops: int,
                      undirected: bool) -> list[dict[str, Any]]:
        """Shortest chain between two entities, following edge direction unless undirected."""

    def semantic_state(self, repo_id: str, commit_sha: str) -> str:
        """Semantic-layer status of a snapshot."""

    def scoped_chunks(self, snapshot: str, vector: list[float], top_k: int) -> list[dict[str, Any]]:
        """Best chunks of one snapshot for a query vector."""

    def global_chunks(self, vector: list[float], top_k: int) -> list[dict[str, Any]]:
        """Best chunks across ready snapshots for a query vector."""

    def chunk_symbols(self, snapshot: str, chunk_id: str) -> list[str]:
        """Named entities that one chunk describes, up to eight."""

    def file_has_entities(self, snapshot: str, file: str) -> bool:
        """True if any entity of the snapshot comes from this file."""


class GraphStore(ReadStore, Protocol):
    """Full provider surface: write path plus reads."""

    def initialize(self) -> None:
        """Create constraints and indexes. Idempotent."""

    def stage_snapshot(self, request: StageRequest) -> str:
        """Write a snapshot hidden from readers. Returns 'created' or 'unchanged'. Raises on a conflicting content hash."""

    def publish_snapshot(self, ref: SnapshotRef) -> None:
        """Make a staged snapshot visible. Idempotent."""

    def summary(self, ref: SnapshotRef) -> SnapshotSummary | None:
        """Counts, hashes and state of one snapshot, or None if it does not exist."""

    def close(self) -> None:
        """Release the connection."""
