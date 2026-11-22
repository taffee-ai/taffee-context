#!/usr/bin/env python3
"""
TurboDataAccess: Database access layer for MCP-Turbo (Milestone 3).
Provides snapshot resolution matching neo4j-query.ts, crowding-safe unified
vector+graph candidate queries with exact-scan fallback, task-ranked structural-only
fallback, and dependency chain traversal.
"""

import re
import json
import logging
from typing import Dict, Any, Optional, List, Set

from turbo_scorer import HybridScorer

logger = logging.getLogger(__name__)

class TurboDataAccess:
    def __init__(self, driver):
        """
        Initialize data access with a neo4j driver or active session provider.
        
        Args:
            driver: neo4j.Driver instance
        """
        self.driver = driver

    def get_snapshot(self, repo: str, commit: Optional[str] = None) -> Dict[str, Any]:
        """
        Resolve ready ContextSnapshot matching context/retrieval/query/neo4j-query.ts.
        
        Args:
            repo: repository identifier (e.g., 'demo-shop')
            commit: optional exact commit SHA
            
        Returns:
            Dict containing snapshot metadata: 'id', 'repoId', 'commitSHA',
            'commitTimestamp', 'ingestionTimestamp', 'semanticStatus'.
            
        Raises:
            ValueError: If repository does not exist or specified commit is not found.
        """
        if not repo:
            raise ValueError("Repository identifier required")

        with self.driver.session(default_access_mode="READ") as session:
            def _resolve(tx):
                # Check if repository exists at all
                repo_check = tx.run(
                    "MATCH (s:ContextSnapshot {repoId: $repo}) RETURN count(s) AS cnt",
                    repo=repo
                ).single()
                if not repo_check or repo_check["cnt"] == 0:
                    raise ValueError(f"Unknown repository: '{repo}'")

                if commit:
                    # Specific commit lookup
                    record = tx.run(
                        """
                        MATCH (s:ContextSnapshot {repoId: $repo, commitSHA: $commit, ready: true})
                        RETURN s.id AS id, s.repoId AS repoId, s.commitSHA AS commitSHA,
                               s.commitTimestamp AS commitTimestamp, s.ingestionTimestamp AS ingestionTimestamp,
                               s.semanticStatus AS semanticStatus,
                               coalesce(s.semanticChunkCount, count { (c:ContextChunk {snapshotId: s.id}) }) AS chunkCount
                        LIMIT 1
                        """,
                        repo=repo, commit=commit
                    ).single()
                    if not record:
                        raise ValueError(f"Unknown commit: '{commit}' for repository '{repo}'")
                    return dict(record)
                else:
                    # Latest ready commit ordered by commitTimestamp DESC, commitSHA DESC
                    record = tx.run(
                        """
                        MATCH (s:ContextSnapshot {repoId: $repo, ready: true})
                        RETURN s.id AS id, s.repoId AS repoId, s.commitSHA AS commitSHA,
                               s.commitTimestamp AS commitTimestamp, s.ingestionTimestamp AS ingestionTimestamp,
                               s.semanticStatus AS semanticStatus,
                               coalesce(s.semanticChunkCount, count { (c:ContextChunk {snapshotId: s.id}) }) AS chunkCount
                        ORDER BY s.commitTimestamp DESC, s.commitSHA DESC
                        LIMIT 1
                        """,
                        repo=repo
                    ).single()
                    if not record:
                        raise ValueError(f"No ready snapshot found for repository '{repo}'")
                    return dict(record)

            return session.execute_read(_resolve)

    def query_candidates(self,
                         snapshot_id: str,
                         query_vector: Optional[List[float]],
                         task_query: str,
                         semantic_ready: bool = True,
                         limit: int = 50) -> List[Dict[str, Any]]:
        """
        Unified single-pass retrieval of candidate chunks and linked AST entities.
        
        Args:
            snapshot_id: JSON string snapshot id (e.g., '["repo","sha"]')
            query_vector: 768-dim embedding vector (optional for structural fallback)
            task_query: task description string
            semantic_ready: True if snapshot has ready semantic vector layer
            limit: maximum distinct candidate chunks to return (default 50)
            
        Returns:
            List of candidate dictionaries with chunk and entity fields.
        """
        limit = max(1, int(limit))

        with self.driver.session(default_access_mode="READ") as session:
            if semantic_ready and query_vector:
                # 1. First fetch top distinct chunks from shared index (DEF-015 limit by distinct chunks)
                cypher_vector_chunks = """
                CALL db.index.vector.queryNodes('context_chunk_embedding', 600, $queryVector)
                YIELD node AS chunk, score AS vectorScore
                WITH collect({c: chunk, s: vectorScore}) AS got
                WITH size(got) AS rawFetched, [x IN got WHERE x.c.snapshotId = $snapshotId] AS mine
                RETURN rawFetched, size(mine) AS matched, [x IN mine[..$limit] | {id: x.c.id, score: x.s}] AS topChunks
                """
                cypher_fallback_chunks = """
                MATCH (c:ContextChunk {snapshotId: $snapshotId})
                WHERE c.embedding IS NOT NULL
                WITH c, vector.similarity.cosine(c.embedding, $queryVector) AS vectorScore
                WHERE vectorScore > 0.3
                ORDER BY vectorScore DESC LIMIT $limit
                RETURN collect({id: c.id, score: vectorScore}) AS topChunks
                """
                # DEF-013: Use OPTIONAL MATCH so chunks without a DESCRIBES link are preserved
                cypher_expand = """
                UNWIND $topChunks AS item
                MATCH (chunk:ContextChunk {snapshotId: $snapshotId, id: item.id})
                WITH chunk, item.score AS vectorScore
                OPTIONAL MATCH (chunk)-[:DESCRIBES]->(entity:ContextEntity {snapshotId: $snapshotId})
                WITH chunk, vectorScore, entity,
                     CASE WHEN entity IS NOT NULL THEN COUNT { (entity)-[:RELATES]-(:ContextEntity) } ELSE 0 END AS entityDegree
                OPTIONAL MATCH (entity)<-[inRel:RELATES]-(caller:ContextEntity {snapshotId: $snapshotId})
                  WHERE inRel.relation IN ['calls', 'imports', 'extends']
                OPTIONAL MATCH (entity)-[outRel:RELATES]->(callee:ContextEntity {snapshotId: $snapshotId})
                  WHERE outRel.relation IN ['calls', 'imports', 'extends']
                RETURN chunk.id AS chunkId, chunk.file AS chunkFile,
                       chunk.startLine AS chunkStartLine, chunk.endLine AS chunkEndLine,
                       vectorScore,
                       coalesce(entity.localId, "") AS entityId,
                       coalesce(entity.label, "") AS entityLabel,
                       coalesce(entity.kind, "file") AS entityKind,
                       coalesce(entity.sourceFile, chunk.file) AS entitySourceFile,
                       coalesce(entity.sourceLocation, "L" + toString(chunk.startLine)) AS entitySourceLocation,
                       entityDegree,
                       collect(DISTINCT caller.label) AS incomingCalls,
                       collect(DISTINCT callee.label) AS outgoingCalls
                ORDER BY vectorScore DESC, chunk.id ASC, coalesce(entity.localId, "") ASC
                """

                def _fetch_vector_and_expand(tx):
                    res = tx.run(cypher_vector_chunks, queryVector=query_vector, snapshotId=snapshot_id, limit=limit).single()
                    raw_fetched = res["rawFetched"] if res else 0
                    matched = res["matched"] if res else 0
                    top_chunks = res["topChunks"] if res else []

                    # DEF-014: If vector path returned fewer distinct chunks than limit while fetch was full (crowding),
                    # trigger exact cosine scan fallback to evaluate all chunks in this snapshot without loss.
                    if matched < limit and raw_fetched >= 600:
                        fb_res = tx.run(cypher_fallback_chunks, queryVector=query_vector, snapshotId=snapshot_id, limit=limit).single()
                        top_chunks = fb_res["topChunks"] if fb_res else []

                    if not top_chunks:
                        return []

                    records = [dict(r) for r in tx.run(cypher_expand, topChunks=top_chunks, snapshotId=snapshot_id)]
                    return records

                return session.execute_read(_fetch_vector_and_expand)

            else:
                # Structural-only fallback (no vector embedding or semantic layer not ready)
                # DEF-011: Rank/filter candidates by lexical match to task terms before degree and limit
                # DEF-012: Without a chunk, use entity's sourceLocation (L<n>) plus bounded window, chunkId=None
                query_tokens = HybridScorer.tokenize(task_query)

                cypher_structural = """
                MATCH (entity:ContextEntity {snapshotId: $snapshotId})
                OPTIONAL MATCH (chunk:ContextChunk {snapshotId: $snapshotId})-[:DESCRIBES]->(entity)
                WITH entity, chunk, COUNT { (entity)-[:RELATES]-(:ContextEntity) } AS entityDegree
                OPTIONAL MATCH (entity)<-[inRel:RELATES]-(caller:ContextEntity {snapshotId: $snapshotId})
                  WHERE inRel.relation IN ['calls', 'imports', 'extends']
                OPTIONAL MATCH (entity)-[outRel:RELATES]->(callee:ContextEntity {snapshotId: $snapshotId})
                  WHERE outRel.relation IN ['calls', 'imports', 'extends']
                RETURN entity.localId AS entityId,
                       entity.label AS entityLabel,
                       entity.kind AS entityKind,
                       entity.sourceFile AS entitySourceFile,
                       entity.sourceLocation AS entitySourceLocation,
                       entityDegree,
                       chunk.id AS chunkId,
                       chunk.file AS chunkFile,
                       chunk.startLine AS chunkStartLine,
                       chunk.endLine AS chunkEndLine,
                       collect(DISTINCT caller.label) AS incomingCalls,
                       collect(DISTINCT callee.label) AS outgoingCalls
                """
                def _fetch_structural_entities(tx):
                    return [dict(r) for r in tx.run(cypher_structural, snapshotId=snapshot_id)]

                all_entities = session.execute_read(_fetch_structural_entities)

                # Score lexical match against task query terms
                def rank_key(e):
                    label_tokens = HybridScorer.tokenize(e.get("entityLabel", ""))
                    file_tokens = HybridScorer.tokenize(e.get("entitySourceFile", ""))
                    combined = label_tokens | file_tokens
                    if not combined or not query_tokens:
                        lex_score = 0.0
                    else:
                        overlap = len(query_tokens & combined)
                        max_len = max(len(query_tokens), len(combined))
                        lex_score = overlap / max_len if max_len > 0 else 0.0
                    has_match = (lex_score > 0.0)
                    deg = int(e.get("entityDegree", 0) or 0)
                    return (has_match, lex_score, deg, str(e.get("chunkId") or ""), str(e.get("entityId") or ""))

                all_entities.sort(key=rank_key, reverse=True)
                selected = all_entities[:limit]

                formatted_records = []
                for item in selected:
                    has_stored_chunk = bool(item.get("chunkId"))
                    if has_stored_chunk:
                        chunk_id = item["chunkId"]
                        chunk_file = item["chunkFile"]
                        start_line = item["chunkStartLine"]
                        end_line = item["chunkEndLine"]
                    else:
                        # DEF-012: Without stored chunk, derive line window around entity sourceLocation L<n>
                        chunk_id = None  # Explicitly None to signal no stored chunk
                        chunk_file = item["entitySourceFile"]
                        loc_str = str(item.get("entitySourceLocation", "") or "")
                        m = re.search(r'\d+', loc_str)
                        loc_line = int(m.group()) if m else 1
                        start_line = max(1, loc_line - 2)
                        end_line = loc_line + 25

                    formatted_records.append({
                        "chunkId": chunk_id,
                        "chunkFile": chunk_file,
                        "chunkStartLine": start_line,
                        "chunkEndLine": end_line,
                        "vectorScore": 0.0,
                        "entityId": item["entityId"],
                        "entityLabel": item["entityLabel"],
                        "entityKind": item["entityKind"],
                        "entitySourceFile": item["entitySourceFile"],
                        "entitySourceLocation": item["entitySourceLocation"],
                        "entityDegree": item["entityDegree"],
                        "incomingCalls": item["incomingCalls"],
                        "outgoingCalls": item["outgoingCalls"]
                    })

                return formatted_records

    def extract_dependency_chain(self, snapshot_id: str, entity_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Traverse RELATES edges between given entities to construct dependency chain.
        
        Args:
            snapshot_id: JSON string snapshot id
            entity_ids: List of ContextEntity localIds
            
        Returns:
            List of edge dicts: {'source': str, 'target': str, 'relation': str, 'sourceFile': str}
        """
        if not entity_ids:
            return []

        cypher = """
        MATCH (src:ContextEntity {snapshotId: $snapshotId})-[r:RELATES]->(tgt:ContextEntity {snapshotId: $snapshotId})
        WHERE src.localId IN $ids AND (tgt.localId IN $ids OR r.relation IN ['calls', 'imports', 'extends'])
        RETURN src.label AS source, tgt.label AS target, r.relation AS relation,
               r.confidence AS confidence,
               src.sourceFile AS sourceFile, tgt.sourceFile AS targetFile
        ORDER BY src.label ASC, tgt.label ASC, r.relation ASC
        LIMIT 100
        """
        with self.driver.session(default_access_mode="READ") as session:
            def _extract(tx):
                return tx.run(cypher, snapshotId=snapshot_id, ids=entity_ids).data()
            return session.execute_read(_extract)
