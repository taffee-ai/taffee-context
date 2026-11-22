"""Neo4j implementation of GraphStore: the write path (stage, publish, summary) and the read path used by the MCP server.

Read queries are copied from context/serving/mcp/server.py and turbo_data.py, so results are byte-identical to the
server's own queries. Source lines are listed in docs/design/005_storage_interface/IMPLEMENTATION.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from neo4j import Driver, GraphDatabase, ManagedTransaction

from .contract import Ambiguous, NotFound, SnapshotRef, SnapshotSummary, StageRequest

SCHEMA_V1 = [
    "CREATE CONSTRAINT context_repository_id IF NOT EXISTS FOR (r:ContextRepository) REQUIRE r.repoId IS UNIQUE",
    "CREATE CONSTRAINT context_snapshot_id IF NOT EXISTS FOR (s:ContextSnapshot) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT context_entity_id IF NOT EXISTS FOR (n:ContextEntity) REQUIRE (n.snapshotId, n.localId) IS UNIQUE",
    "CREATE INDEX context_snapshot_resolution IF NOT EXISTS FOR (s:ContextSnapshot) ON (s.repoId, s.commitTimestamp)",
]
SCHEMA_V2 = [
    "CREATE CONSTRAINT context_chunk_id IF NOT EXISTS FOR (c:ContextChunk) REQUIRE (c.snapshotId, c.id) IS UNIQUE",
    "CREATE VECTOR INDEX context_chunk_embedding IF NOT EXISTS FOR (c:ContextChunk) ON (c.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}",
]
BATCH = 500
ALREADY_EXISTS = "Neo.ClientError.Schema.EquivalentSchemaRuleAlreadyExists"
SEARCH_FETCH = 600  # the vector index is global across snapshots: over-fetch, then keep one snapshot's rows
CHUNK_FIELDS = ("{id: x.n.id, file: x.n.file, s: x.n.startLine, e: x.n.endLine, score: x.score, cut: x.n.truncated, "
                "tcut: coalesce(x.n.tokenTruncated, false), emb: x.n.embeddedChars, chars: x.n.charCount, snap: x.n.snapshotId}")


def snapshot_id(repo_id: str, commit_sha: str) -> str:
    """The snapshot id the TypeScript loader stores and the MCP server reads: JSON of [repoId, commit SHA]."""
    return json.dumps([repo_id, commit_sha], separators=(",", ":"), ensure_ascii=False)


class Neo4jStore:
    """Neo4j provider: the write path (stage, publish, summary) and the read path the MCP service uses."""
    def __init__(self, driver: Driver, database: str = "neo4j", read_timeout: float = 15.0) -> None:
        """Keep the driver, the database name and the read timeout in seconds."""
        self._driver = driver
        self._database = database
        self._read_timeout = read_timeout

    @classmethod
    def connect(cls, uri: str, user: str, password: str, database: str = "neo4j", read_timeout: float = 15.0,
                pool_size: int = 4) -> "Neo4jStore":
        """Create a store from connection settings. No connection is opened until first use."""
        driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=3,
                                      max_connection_pool_size=pool_size)
        return cls(driver, database, read_timeout)

    def close(self) -> None:
        """Close the driver and its connection pool."""
        self._driver.close()

    # ------------------------------------------------------------------ write path

    def _session(self):
        """Open a session on the configured database."""
        return self._driver.session(database=self._database)

    def initialize(self) -> None:
        """Create constraints and indexes, then wait for indexes to come online. Idempotent."""
        with self._session() as session:
            for statement in SCHEMA_V1 + SCHEMA_V2:
                try:
                    session.run(statement).consume()
                except Exception as error:  # noqa: BLE001 - the driver error carries the code
                    if getattr(error, "code", None) != ALREADY_EXISTS:
                        raise
            session.run("CALL db.awaitIndexes(30)").consume()

    def stage_snapshot(self, request: StageRequest) -> str:
        """Write a snapshot hidden from readers. Returns created or unchanged; raises ValueError on a conflicting content hash."""
        sid = snapshot_id(request.ref.repo_id, request.ref.commit_sha)
        timeout = max(60.0, 30.0 + ((len(request.nodes) + len(request.edges)) // 500 + 1) * 5.0)
        with self._session() as session:
            tx = session.begin_transaction(timeout=timeout)
            try:
                outcome = self._stage_tx(tx, request, sid)
                tx.commit()
                return outcome
            except BaseException:
                tx.rollback()
                raise

    @staticmethod
    def _stage_tx(tx: ManagedTransaction, request: StageRequest, sid: str) -> str:
        # MERGE plus a property write takes the repository write lock before the existence check.
        """Transaction body of stage_snapshot: repository lock, conflict check, nodes, edges, then the staged flag."""
        tx.run(
            "MERGE (r:ContextRepository {repoId: $repoId}) SET r.writeSequence = coalesce(r.writeSequence, 0) + 1",
            repoId=request.ref.repo_id,
        ).consume()
        existing = tx.run("MATCH (s:ContextSnapshot {id: $id}) RETURN s.contentHash AS hash", id=sid).single()
        if existing is not None:
            if existing["hash"] != request.content_hash:
                raise ValueError("Immutable snapshot conflict: graph content or extractor version differs")
            return "unchanged"
        metadata = {
            **request.metadata,
            "repoId": request.ref.repo_id,
            "commitSHA": request.ref.commit_sha,
            "id": sid,
            "contentHash": request.content_hash,
            "artifactHash": request.artifact_hash,
            "ingestionTimestamp": datetime.now(timezone.utc).isoformat(),
            "schemaVersion": 1,
            "nodeCount": len(request.nodes),
            "edgeCount": len(request.edges),
        }
        tx.run(
            "MATCH (r:ContextRepository {repoId: $repoId}) "
            "CREATE (s:ContextSnapshot $metadata) CREATE (r)-[:HAS_SNAPSHOT]->(s)",
            repoId=request.ref.repo_id, metadata=metadata,
        ).consume()
        nodes = [vars(n) for n in request.nodes]
        for i in range(0, len(nodes), BATCH):
            tx.run(
                "MATCH (s:ContextSnapshot {id: $id}) UNWIND $nodes AS n "
                "CREATE (e:ContextEntity {snapshotId: $id, localId: n.local_id, label: n.label, kind: n.kind, "
                "sourceFile: n.source_file, sourceLocation: n.source_location, community: n.community, "
                "nativeOrder: n.native_order, nativePropertiesJson: n.native_properties_json}) "
                "CREATE (s)-[:HAS_ENTITY]->(e)",
                id=sid, nodes=nodes[i:i + BATCH],
            ).consume()
        edges = [vars(e) for e in request.edges]
        for i in range(0, len(edges), BATCH):
            tx.run(
                "UNWIND $edges AS e "
                "MATCH (a:ContextEntity {snapshotId: $id, localId: e.source}) "
                "MATCH (b:ContextEntity {snapshotId: $id, localId: e.target}) "
                "CREATE (a)-[:RELATES {relation: e.relation, confidence: e.confidence, sourceFile: e.source_file, "
                "sourceLocation: e.source_location, context: e.context, nativeOrder: e.native_order, "
                "nativePropertiesJson: e.native_properties_json}]->(b)",
                id=sid, edges=edges[i:i + BATCH],
            ).consume()
        tx.run("MATCH (s:ContextSnapshot {id: $id}) SET s.ready = false, s.staged = true", id=sid).consume()
        return "created"

    def publish_snapshot(self, ref: SnapshotRef) -> None:
        """Make a staged snapshot visible. Raises ValueError if the snapshot does not exist."""
        sid = snapshot_id(ref.repo_id, ref.commit_sha)
        with self._session() as session:
            record = session.execute_write(
                lambda tx: tx.run(
                    "MATCH (s:ContextSnapshot {id: $id}) SET s.ready = true, s.staged = false RETURN s.id AS id", id=sid
                ).single()
            )
        if record is None:
            raise ValueError("Snapshot to publish does not exist")

    def summary(self, ref: SnapshotRef) -> SnapshotSummary | None:
        """Counts, hashes and state of one snapshot, or None if it does not exist."""
        sid = snapshot_id(ref.repo_id, ref.commit_sha)
        with self._session() as session:
            row = session.run(
                """MATCH (s:ContextSnapshot {id: $id})
                   OPTIONAL MATCH (s)-[:HAS_ENTITY]->(n:ContextEntity)
                   WITH s, count(n) AS nodes
                   OPTIONAL MATCH (a:ContextEntity {snapshotId: $id})-[e:RELATES]->(b:ContextEntity {snapshotId: $id})
                   RETURN s.ready AS ready, s.staged AS staged, s.contentHash AS hash, s.artifactHash AS artifactHash,
                          s.nodeCount AS declaredNodes, s.edgeCount AS declaredEdges, nodes, count(e) AS edges,
                          s.semanticStatus AS semanticStatus""",
                id=sid,
            ).single()
        if row is None:
            return None
        return SnapshotSummary(
            snapshot_id=sid, ready=bool(row["ready"]), staged=bool(row["staged"]),
            content_hash=row["hash"], artifact_hash=row["artifactHash"],
            declared_nodes=int(row["declaredNodes"]), declared_edges=int(row["declaredEdges"]),
            nodes=int(row["nodes"]), edges=int(row["edges"]), semantic_status=row["semanticStatus"],
        )

    # ------------------------------------------------------------------ read path

    def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        """Read-only transaction with a timeout, as the MCP server's own helper ran it."""
        with self._driver.session(database=self._database, default_access_mode="READ") as session:
            tx = session.begin_transaction(timeout=self._read_timeout)
            try:
                return [record.data() for record in tx.run(query, **params)]
            finally:
                tx.close()

    def _require_ready(self, sid: str) -> None:
        """Staged or missing snapshots are never read (requirement R5)."""
        if not self._read("MATCH (h:ContextSnapshot {id:$s, ready:true}) RETURN 1 AS x LIMIT 1", s=sid):
            raise NotFound(f"no ready snapshot for repo '{json.loads(sid)[0]}' (see list_repos)")

    def list_repos_page(self, query: str, limit: int, offset: int, all_commits: bool) -> tuple[int, list[dict[str, Any]]]:
        """Ready repos, or every ready commit, filtered by name, with the total and one page."""
        base = "MATCH (h:ContextSnapshot {ready:true}) WHERE $q = '' OR toLower(h.repoId) CONTAINS toLower($q) "
        if all_commits:
            total = self._read(base + "RETURN count(h) AS n", q=query)[0]["n"]
            rows = self._read(base + "RETURN h.repoId AS repo, h.commitSHA AS commit, h.commitTimestamp AS committed, "
                              "h.nodeCount AS entities, h.edgeCount AS edges, h.semanticStatus AS semantic, "
                              "h.semanticChunkCount AS chunks ORDER BY repo, committed DESC SKIP $o LIMIT $l",
                              q=query, o=offset, l=limit)
        else:
            total = self._read(base + "RETURN count(DISTINCT h.repoId) AS n", q=query)[0]["n"]
            rows = self._read(base + "WITH h ORDER BY h.commitTimestamp DESC, h.commitSHA DESC WITH h.repoId AS repo, collect(h) AS hs "
                              "RETURN repo, hs[0].commitSHA AS commit, hs[0].commitTimestamp AS committed, "
                              "hs[0].nodeCount AS entities, hs[0].edgeCount AS edges, hs[0].semanticStatus AS semantic, "
                              "hs[0].semanticChunkCount AS chunks, size(hs) AS commits_available "
                              "ORDER BY repo SKIP $o LIMIT $l", q=query, o=offset, l=limit)
        return total, rows

    def resolve_snapshot(self, repo_id: str, commit_prefix: str | None = None) -> str:
        """Commit of the newest ready snapshot, or of the one matching the prefix. Raises NotFound or Ambiguous."""
        if commit_prefix:
            rows = self._read("MATCH (h:ContextSnapshot {repoId:$r, ready:true}) WHERE h.commitSHA STARTS WITH $c "
                              "RETURN h.commitSHA AS sha LIMIT 2", r=repo_id, c=commit_prefix)
            if len(rows) != 1:
                raise Ambiguous(f"commit '{commit_prefix}' matches {len(rows)} ready snapshots of {repo_id}")
            return rows[0]["sha"]
        rows = self._read("MATCH (h:ContextSnapshot {repoId:$r, ready:true}) RETURN h.commitSHA AS sha "
                          "ORDER BY h.commitTimestamp DESC, h.commitSHA DESC LIMIT 1", r=repo_id)
        if not rows:
            raise NotFound(f"no ready snapshot for repo '{repo_id}' (see list_repos)")
        return rows[0]["sha"]

    def stats(self, repo_id: str, commit_sha: str) -> dict[str, Any]:
        """Node, community, edge-confidence and chunk counts for one snapshot. Raises NotFound if not ready."""
        self._require_ready(snapshot_id(repo_id, commit_sha))
        s = snapshot_id(repo_id, commit_sha)
        nodes = self._read("MATCH (n:ContextEntity {snapshotId:$s}) RETURN count(n) AS nodes, "
                           "count(DISTINCT n.community) AS communities", s=s)[0]
        edges = self._read("MATCH (:ContextEntity {snapshotId:$s})-[r:RELATES]->(:ContextEntity {snapshotId:$s}) "
                           "RETURN coalesce(r.confidence,'unknown') AS confidence, count(r) AS n", s=s)
        chunks = self._read("MATCH (k:ContextChunk {snapshotId:$s}) RETURN count(k) AS n", s=s)[0]["n"]
        return {"nodes": nodes, "edges": edges, "chunks": chunks}

    def find_nodes(self, repo_id: str, commit_sha: str, label: str) -> list[dict[str, Any]]:
        """Exact label (case-insensitive) or id; then a suffix match; then a substring match."""
        self._require_ready(snapshot_id(repo_id, commit_sha))
        query = ("MATCH (n:ContextEntity {snapshotId:$s}) WHERE %s "
                 "RETURN n.localId AS id, n.label AS label, n.sourceFile AS file, n.sourceLocation AS loc, n.kind AS kind "
                 "ORDER BY n.nativeOrder LIMIT 5")
        low = label.lower()
        for cond in ("toLower(n.label) = $l OR n.localId = $raw",
                     "toLower(n.label) ENDS WITH $l",
                     "toLower(n.label) CONTAINS $l"):
            rows = self._read(query % cond, s=snapshot_id(repo_id, commit_sha), l=low, raw=label)
            if rows:
                return rows
        return []

    def neighbours(self, repo_id: str, commit_sha: str, node_id: str, relation: str | None, limit: int) -> list[dict[str, Any]]:
        """Direct connections of one node, optionally limited to one relation. Raises NotFound if not ready."""
        self._require_ready(snapshot_id(repo_id, commit_sha))
        return self._read("MATCH (n:ContextEntity {snapshotId:$s, localId:$id})-[r:RELATES]-(m:ContextEntity) "
                          "WHERE $rel IS NULL OR toUpper(r.relation) = toUpper($rel) "
                          "RETURN r.relation AS rel, startNode(r).localId = $id AS outgoing, r.confidence AS conf, "
                          "m.localId AS id, m.label AS label, m.sourceFile AS file, m.sourceLocation AS loc "
                          "ORDER BY rel, label LIMIT $lim", s=snapshot_id(repo_id, commit_sha), id=node_id, rel=relation,
                          lim=limit)

    def read_graph(self, repo_id: str, commit_sha: str) -> dict[str, list[dict[str, Any]]]:
        """Every node and edge of a snapshot, with native properties. Raises NotFound if not ready."""
        self._require_ready(snapshot_id(repo_id, commit_sha))
        s = snapshot_id(repo_id, commit_sha)
        nodes = self._read("MATCH (n:ContextEntity {snapshotId:$s}) RETURN n.nativeOrder AS ord, "
                           "n.nativePropertiesJson AS p, n.localId AS id", s=s)
        edges = self._read("MATCH (a:ContextEntity {snapshotId:$s})-[r:RELATES]->(b:ContextEntity {snapshotId:$s}) "
                           "RETURN r.nativeOrder AS ord, r.nativePropertiesJson AS p", s=s)
        return {"nodes": nodes, "edges": edges}

    def community_members(self, repo_id: str, commit_sha: str, community_id: str, limit: int) -> list[dict[str, Any]]:
        """Entities of one community, up to limit rows. Raises NotFound if not ready."""
        self._require_ready(snapshot_id(repo_id, commit_sha))
        return self._read("MATCH (n:ContextEntity {snapshotId:$s, community:$id}) RETURN n.label AS label, "
                          "n.sourceFile AS file, n.sourceLocation AS loc ORDER BY label LIMIT $lim",
                          s=snapshot_id(repo_id, commit_sha), id=community_id, lim=limit)

    def shortest_path(self, repo_id: str, commit_sha: str, source_id: str, target_id: str, hops: int,
                      undirected: bool) -> list[dict[str, Any]]:
        """Shortest chain between two entities within hops. Raises NotFound if not ready."""
        self._require_ready(snapshot_id(repo_id, commit_sha))
        arrow = "-" if undirected else "->"
        return self._read(f"MATCH (a:ContextEntity {{snapshotId:$s, localId:$a}}), (z:ContextEntity {{snapshotId:$s, localId:$z}}) "
                          f"MATCH p = shortestPath((a)-[:RELATES*..{hops}]{arrow}(z)) "
                          "RETURN [n IN nodes(p) | n.label] AS names, [r IN relationships(p) | r.relation] AS rels, "
                          "[i IN range(0, size(relationships(p)) - 1) | startNode(relationships(p)[i]) = nodes(p)[i]] AS fwd",
                          s=snapshot_id(repo_id, commit_sha), a=source_id, z=target_id)

    def semantic_state(self, repo_id: str, commit_sha: str) -> str:
        """Semantic-layer status of a snapshot. Raises NotFound if not ready."""
        self._require_ready(snapshot_id(repo_id, commit_sha))
        return self._read("MATCH (h:ContextSnapshot {id:$s}) RETURN h.semanticStatus AS st",
                          s=snapshot_id(repo_id, commit_sha))[0]["st"]

    def scoped_chunks(self, snapshot: str, vector: list[float], top_k: int) -> list[dict[str, Any]]:
        """Best chunks of one snapshot for a vector, with an exact-scan fallback when the shared index is crowded."""
        self._require_ready(snapshot)
        """Top chunks of one snapshot: the global index first; if other snapshots crowd it out, an exact scan of this one."""
        r = self._read("CALL db.index.vector.queryNodes('context_chunk_embedding', $fetch, $v) YIELD node, score "
                       "WITH collect({n: node, score: score}) AS got "
                       "WITH size(got) AS fetched, [x IN got WHERE x.n.snapshotId = $s] AS mine "
                       "RETURN fetched, size(mine) AS matched, [x IN mine[..$k] | " + CHUNK_FIELDS + "] AS top",
                       fetch=SEARCH_FETCH, v=vector, s=snapshot, k=top_k)[0]
        if r["matched"] < top_k and r["fetched"] >= SEARCH_FETCH:
            r = self._read("MATCH (c:ContextChunk {snapshotId: $s}) WHERE c.embedding IS NOT NULL "
                           "WITH c, vector.similarity.cosine(c.embedding, $v) AS score ORDER BY score DESC "
                           "WITH collect({n: c, score: score}) AS got "
                           "RETURN size(got) AS fetched, size(got) AS matched, [x IN got[..$k] | " + CHUNK_FIELDS + "] AS top",
                           s=snapshot, v=vector, k=top_k)[0]
        return r["top"]

    def global_chunks(self, vector: list[float], top_k: int) -> list[dict[str, Any]]:
        """Best chunks across ready snapshots for a vector."""
        return self._read("CALL db.index.vector.queryNodes('context_chunk_embedding', $fetch, $v) YIELD node, score "
                          "WHERE EXISTS { MATCH (h:ContextSnapshot {id: node.snapshotId, ready: true, semanticStatus: 'ready'}) } "
                          "WITH collect({n: node, score: score}) AS got "
                          "RETURN [x IN got[..$k] | " + CHUNK_FIELDS + "] AS top",
                          fetch=SEARCH_FETCH, v=vector, k=top_k)[0]["top"]

    def chunk_symbols(self, snapshot: str, chunk_id: str) -> list[str]:
        """Named entities a chunk describes, up to eight. Empty list if none."""
        self._require_ready(snapshot)
        rows = self._read("MATCH (c:ContextChunk {snapshotId:$s, id:$id})-[:DESCRIBES]->(e:ContextEntity) "
                          "WITH e ORDER BY toInteger(substring(e.sourceLocation, 1)), e.localId "
                          "RETURN collect(e.label + ' ' + e.sourceLocation)[..8] AS symbols", s=snapshot, id=chunk_id)
        return rows[0]["symbols"] if rows else []

    def file_has_entities(self, snapshot: str, file: str) -> bool:
        """True if any entity of the snapshot comes from this file. Raises NotFound if not ready."""
        self._require_ready(snapshot)
        return bool(self._read("MATCH (n:ContextEntity {snapshotId:$s}) WHERE n.sourceFile = $f RETURN 1 AS x LIMIT 1",
                               s=snapshot, f=file))
