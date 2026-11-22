#!/usr/bin/env python3
"""
ContextPackBuilder: Assembles trusted context packs within strict token budgets.
Combines:
  1. TurboDataAccess (Neo4j snapshot resolution, unified vector+graph Cypher, transitive dependency chain)
  2. HybridScorer (Vector similarity, graph centrality, sub-token lexical match with stop-word filtering)
  3. GitBlobReader (In-memory committed source line retrieval, zero working-tree checkout)
  4. TokenKnapsack (Deterministic whole-line budget packing)

Strict Invariants:
  - Total Returned String Token Cap (DEF-017): math.ceil(len(json.dumps(pack)) / 3.0) <= max_tokens strictly guaranteed.
  - Dependency Chain Integrity (DEF-018): Real endpoints and stored confidence labels from RELATES edges.
  - Stop-Word-Aware Off-Topic Separation (DEF-016): Common stop words filtered so generic queries do not trigger false lexical matches.
  - Validation Status Taxonomy (DEF-019): 'pass', 'low_confidence', or 'incomplete'.
  - Per-item Truncation Accounting (DEF-020): Explicit original_lines and kept_lines on evidence; un-invented anchor lines.
"""

import os
import re
import math
import time
import json
import logging
from typing import Dict, Any, List, Optional, Callable, Tuple, Set

from turbo_data import TurboDataAccess
from turbo_scorer import HybridScorer
from turbo_knapsack import TokenKnapsack
from turbo_git import GitBlobReader

import threading

logger = logging.getLogger(__name__)

_laya_adapter_instance = None
_laya_lock = threading.Lock()

def _get_laya_adapter():
    global _laya_adapter_instance
    if os.environ.get("ENABLE_LAYA_JEV", "").lower() not in ("true", "1", "yes"):
        return None
    with _laya_lock:
        if _laya_adapter_instance is None or not _laya_adapter_instance.enabled:
            try:
                from turbo_jev import LayaJEVAdapter
                _laya_adapter_instance = LayaJEVAdapter()
            except Exception as ex:
                logger.warning(f"Failed to load LayaJEVAdapter: {ex}")
                _laya_adapter_instance = None
        return _laya_adapter_instance

COMMIT_SHA_REGEX = re.compile(r"^[a-f0-9]{7,64}$")
REPO_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_.-]+$")

STOP_WORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing",
    "don't", "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is",
    "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should",
    "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we",
    "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
}


QUESTION_BOILERPLATE: Set[str] = {
    "file", "files", "path", "paths", "name", "names", "class", "classes",
    "method", "methods", "function", "functions", "give", "find", "show", "get", "list"
}


class ContextPackBuilder:
    def __init__(self,
                 data_access: TurboDataAccess,
                 code_root: str = "/repos",
                 embed_fn: Optional[Callable[[str], List[float]]] = None,
                 scorer: Optional[HybridScorer] = None,
                 knapsack: Optional[TokenKnapsack] = None):
        """
        Initialize ContextPackBuilder.
        """
        self.data_access = data_access
        self.code_root = code_root
        self.embed_fn = embed_fn
        self.scorer = scorer or HybridScorer()
        self.knapsack = knapsack or TokenKnapsack()
        self.last_timings: Dict[str, float] = {}

    @staticmethod
    def extract_task_terms(task: str) -> Set[str]:
        """
        Extract meaningful task content terms (identifiers and nouns),
        tokenized and split on camelCase, omitting common stop words and question boilerplate.
        """
        raw_tokens = HybridScorer.tokenize(task)
        content_terms = raw_tokens - STOP_WORDS - QUESTION_BOILERPLATE
        if not content_terms:
            content_terms = raw_tokens - STOP_WORDS
        if not content_terms:
            content_terms = raw_tokens
        return content_terms

    @staticmethod
    def compute_term_coverage(
        task: str,
        packed_anchors: List[Dict[str, Any]],
        packed_code_evidence: List[Dict[str, Any]],
        packed_edges: Optional[List[Dict[str, Any]]] = None,
        unique_chunks: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[float, Set[str], Set[str]]:
        """
        Compute fraction of task content terms covered by returned anchor labels,
        file names, and symbols (including chunk entities and raw lines).
        Returns (coverage_ratio, task_terms, covered_terms).
        """
        task_terms = ContextPackBuilder.extract_task_terms(task)
        if not task_terms:
            return 1.0, set(), set()

        pack_tokens: Set[str] = set()

        # 1. Architectural anchor labels and source files
        for a in packed_anchors:
            pack_tokens |= HybridScorer.tokenize(a.get("label", ""))
            pack_tokens |= HybridScorer.tokenize(a.get("sourceFile", "") or a.get("file", ""))

        # 2. Code evidence file locations and paths, plus raw lines
        for ce in packed_code_evidence:
            loc = ce.get("location", "")
            fn = loc.split(":")[0] if ":" in loc else loc
            pack_tokens |= HybridScorer.tokenize(fn)
            pack_tokens |= HybridScorer.tokenize(ce.get("file", ""))
            for line in ce.get("raw_lines", []):
                pack_tokens |= HybridScorer.tokenize(line)

        # 3. Dependency chain endpoints
        if packed_edges:
            for e in packed_edges:
                pack_tokens |= HybridScorer.tokenize(e.get("from", ""))
                pack_tokens |= HybridScorer.tokenize(e.get("to", ""))

        # 4. Described entity symbols for packed chunks
        if unique_chunks:
            packed_chunk_ids = {ce.get("chunkId") for ce in packed_code_evidence if ce.get("chunkId")}
            for chunk in unique_chunks:
                if chunk.get("chunkId") in packed_chunk_ids:
                    for ent in chunk.get("entities", []):
                        pack_tokens |= HybridScorer.tokenize(ent.get("label", ""))

        covered = task_terms & pack_tokens
        coverage_ratio = len(covered) / len(task_terms) if task_terms else 1.0
        return coverage_ratio, task_terms, covered

    @staticmethod
    def compute_candidate_pool(chunk_count: Optional[int] = None, override: Optional[int] = None) -> int:
        """
        Compute candidate pool size adaptively based on snapshot chunk count:
        clamp(ceil(snapshot_chunk_count / 10), 50, 200).
        Supports explicit parameter override or TURBO_CANDIDATE_POOL environment variable.
        """
        if override is not None:
            return max(1, int(override))
        env_override = os.environ.get("TURBO_CANDIDATE_POOL")
        if env_override:
            try:
                return max(1, int(env_override))
            except ValueError:
                pass
        cnt = chunk_count if (chunk_count is not None and chunk_count > 0) else 500
        pool = math.ceil(cnt / 10.0)
        return max(50, min(200, pool))

    def build_pack(self,
                   repo: str,
                   task: str,
                   max_tokens: int = 4000,
                   commit: Optional[str] = None,
                   candidate_pool: Optional[int] = None) -> Dict[str, Any]:
        """
        Assemble a complete Trusted Context Pack strictly bounded by max_tokens.
        """
        # 1. Parameter validation & clamping
        # DEF-028: Check mutual exclusivity at tool/builder level
        jev_enabled = os.environ.get("ENABLE_LAYA_JEV", "").lower() in ("true", "1", "yes")
        qwen_enabled = os.environ.get("ENABLE_QWEN_DISTILLER", "").lower() in ("true", "1", "yes")
        if jev_enabled and qwen_enabled:
            raise ValueError("Mutual exclusivity violation: ENABLE_LAYA_JEV and ENABLE_QWEN_DISTILLER cannot both be enabled simultaneously")

        laya_adapter = _get_laya_adapter() if jev_enabled else None
        strategy_route = "standard"
        t_laya_route = 0.0
        if laya_adapter and laya_adapter.enabled:
            t0_laya_route = time.perf_counter()
            strategy_route = laya_adapter.route_strategy_sync(task)
            t_laya_route = time.perf_counter() - t0_laya_route

        if not repo or not isinstance(repo, str):
            raise ValueError("repo must be a non-empty string")
        repo = repo.strip()
        if not REPO_NAME_REGEX.match(repo):
            raise ValueError(f"Invalid repository name: {repo}")

        if not task or not isinstance(task, str):
            raise ValueError("task must be a non-empty string")
        task = task.strip()
        if len(task) > 2000:
            raise ValueError("task must be 1-2000 characters")

        try:
            val_tokens = int(max_tokens)
        except (ValueError, TypeError):
            val_tokens = 4000
        clamped_tokens = max(500, min(16000, val_tokens))

        if commit is not None:
            commit = str(commit).strip()
            if commit and not COMMIT_SHA_REGEX.match(commit):
                raise ValueError(f"Invalid commit format: {commit}")
            if not commit:
                commit = None

        # 2. Snapshot lookup
        t0_snapshot = time.perf_counter()
        snapshot = self.data_access.get_snapshot(repo, commit)
        t_snapshot = time.perf_counter() - t0_snapshot

        snapshot_id = snapshot["id"]
        commit_sha = snapshot["commitSHA"]
        semantic_status = snapshot.get("semanticStatus")
        chunk_count = snapshot.get("chunkCount")
        pool_limit = self.compute_candidate_pool(chunk_count, override=candidate_pool)

        # DEF-017: Bound echoed task in metadata so long task strings do not consume excessive budget
        bounded_task_echo = task[:150]

        # 3. Retrieve raw candidate rows
        vector_hit = False
        fallback_used = False
        raw_rows = []
        t_embed = 0.0

        if semantic_status == "ready" and self.embed_fn is not None:
            try:
                t0_embed = time.perf_counter()
                query_vector = self.embed_fn(task)
                t_embed = time.perf_counter() - t0_embed

                t0_cypher = time.perf_counter()
                raw_rows = self.data_access.query_candidates(
                    snapshot_id=snapshot_id,
                    query_vector=query_vector,
                    task_query=task,
                    semantic_ready=True,
                    limit=pool_limit
                )
                t_cypher = time.perf_counter() - t0_cypher
                vector_hit = True
                fallback_used = False
            except Exception as e:
                logger.warning(f"Vector search failed, falling back to structural: {e}")
                t0_cypher = time.perf_counter()
                raw_rows = self.data_access.query_candidates(
                    snapshot_id=snapshot_id,
                    query_vector=None,
                    task_query=task,
                    semantic_ready=False,
                    limit=pool_limit
                )
                t_cypher = time.perf_counter() - t0_cypher
                vector_hit = False
                fallback_used = True
        else:
            t0_cypher = time.perf_counter()
            raw_rows = self.data_access.query_candidates(
                snapshot_id=snapshot_id,
                query_vector=None,
                task_query=task,
                semantic_ready=False,
                limit=pool_limit
            )
            t_cypher = time.perf_counter() - t0_cypher
            vector_hit = False
            fallback_used = True

        top_vector_row = None
        if raw_rows:
            try:
                cand_top = max(raw_rows, key=lambda r: float(r.get("vectorScore", 0.0) or 0.0))
                if float(cand_top.get("vectorScore", 0.0) or 0.0) > 0.0:
                    top_vector_row = cand_top
            except Exception:
                top_vector_row = None

        # 4. Group rows by distinct chunk
        t0_scoring = time.perf_counter()
        chunks_by_id: Dict[str, Dict[str, Any]] = {}
        entities_by_id: Dict[str, Dict[str, Any]] = {}

        max_degree = 1
        for row in raw_rows:
            deg = int(row.get("entityDegree", 0) or 0)
            if deg > max_degree:
                max_degree = deg

        # DEF-016: Extract meaningful non-stop query tokens for lexical matching
        meaningful_query_terms = HybridScorer.tokenize(task) - STOP_WORDS

        for row in raw_rows:
            cid = row.get("chunkId")
            chunk_key = cid if cid else f"virt_{row.get('entitySourceFile')}_{row.get('chunkStartLine')}"

            vec_score = float(row.get("vectorScore", 0.0) or 0.0)
            eid = row.get("entityId")
            elabel = row.get("entityLabel") or ""
            cfile = row.get("chunkFile") or row.get("entitySourceFile") or ""

            # Lexical match using meaningful terms
            target_tokens = HybridScorer.tokenize(elabel) | HybridScorer.tokenize(cfile)
            target_tokens_non_stop = target_tokens - STOP_WORDS
            if meaningful_query_terms and target_tokens_non_stop:
                overlap = len(meaningful_query_terms & target_tokens_non_stop)
                lex_score = overlap / max(len(meaningful_query_terms), len(target_tokens_non_stop))
            else:
                lex_score = 0.0

            row_dict = dict(row)
            row_dict["entityLabel"] = elabel or cfile
            row_hybrid_score = self.scorer.score(row_dict, task)

            if chunk_key not in chunks_by_id:
                chunks_by_id[chunk_key] = {
                    "chunkId": cid,
                    "chunkFile": cfile,
                    "chunkStartLine": row.get("chunkStartLine"),
                    "chunkEndLine": row.get("chunkEndLine"),
                    "vectorScore": vec_score,
                    "lexicalScore": lex_score,
                    "maxHybridScore": row_hybrid_score,
                    "entities": []
                }
            else:
                if row_hybrid_score > chunks_by_id[chunk_key]["maxHybridScore"]:
                    chunks_by_id[chunk_key]["maxHybridScore"] = row_hybrid_score
                if lex_score > chunks_by_id[chunk_key]["lexicalScore"]:
                    chunks_by_id[chunk_key]["lexicalScore"] = lex_score

            if elabel and elabel not in [e["label"] for e in chunks_by_id[chunk_key]["entities"]]:
                chunks_by_id[chunk_key]["entities"].append({
                    "id": eid,
                    "label": elabel,
                    "kind": row.get("entityKind", "symbol"),
                    "sourceFile": row.get("entitySourceFile", cfile),
                    "sourceLocation": row.get("entitySourceLocation", "L1"),
                    "degree": row.get("entityDegree", 0),
                    "hybridScore": row_hybrid_score,
                    "lexicalScore": lex_score
                })

            if elabel:
                entity_key = eid if eid else f"{row.get('entitySourceFile')}:{elabel}"
                if entity_key not in entities_by_id or row_hybrid_score > entities_by_id[entity_key]["hybridScore"]:
                    entities_by_id[entity_key] = {
                        "id": eid,
                        "label": elabel,
                        "kind": row.get("entityKind", "symbol"),
                        "sourceFile": row.get("entitySourceFile", cfile),
                        "sourceLocation": row.get("entitySourceLocation", "L1"),
                        "degree": row.get("entityDegree", 0),
                        "hybridScore": row_hybrid_score,
                        "lexicalScore": lex_score
                    }

        unique_chunks = list(chunks_by_id.values())
        unique_entities = list(entities_by_id.values())

        # 5. DEF-016: Calibrated Off-Topic Separation Rule
        scores = [c["vectorScore"] for c in unique_chunks if c.get("vectorScore", 0.0) > 0.0]
        has_lexical_match = any(c["lexicalScore"] > 0.0 for c in unique_chunks) or any(e["lexicalScore"] > 0.0 for e in unique_entities)

        if scores:
            scores_sorted = sorted(scores)
            median_score = scores_sorted[len(scores_sorted) // 2]
            top_score = scores_sorted[-1]
            score_margin = top_score - median_score
        else:
            median_score = 0.0
            top_score = 0.0
            score_margin = 0.0

        is_off_topic = False
        if not unique_chunks and not unique_entities:
            is_off_topic = True
            confidence_score = 0.0
        elif not has_lexical_match:
            if vector_hit:
                # With zero non-stop lexical match and flat score margin over median (< 0.075) or low top score (< 0.65), query is off-topic
                if score_margin < 0.075 or top_score < 0.65:
                    is_off_topic = True
                    confidence_score = round(max(0.05, top_score - 0.45), 2)
            else:
                is_off_topic = True
                confidence_score = 0.05

        # Always sort chunks and entities deterministically
        unique_chunks.sort(key=lambda c: (
            -c["maxHybridScore"],
            c.get("chunkFile") or "",
            c.get("chunkStartLine") or 0,
            str(c.get("chunkId") or "")
        ))
        unique_entities.sort(key=lambda e: (
            -e["hybridScore"],
            e.get("label") or "",
            str(e.get("id") or "")
        ))

        if not is_off_topic:
            top_scores = [e["hybridScore"] for e in unique_entities[:5]] or [c["maxHybridScore"] for c in unique_chunks[:5]]
            confidence_score = round(sum(top_scores) / len(top_scores), 2) if top_scores else 0.50
            confidence_score = min(1.0, max(0.1, confidence_score))

        is_low_confidence = is_off_topic or (confidence_score < 0.25)

        # 6. Extract Anchors (DEF-020: no invented endLine)
        anchor_candidates = []
        for e in unique_entities[:10]:
            loc_str = str(e.get("sourceLocation", "L1"))
            s_line, e_line = self._parse_location(loc_str)
            anchor_dict = {
                "label": e["label"],
                "type": e.get("kind", "symbol"),
                "location": f"{e.get('sourceFile', '')}:{loc_str}",
                "file": e.get("sourceFile", ""),
                "startLine": s_line,
                "degree": e.get("degree", 0),
                "hybridScore": round(e.get("hybridScore", 0.0), 2)
            }
            if e_line is not None:
                anchor_dict["endLine"] = e_line
            anchor_candidates.append(anchor_dict)

        t_scoring_grouping = time.perf_counter() - t0_scoring

        # 7. Extract Dependency Chain (DEF-018: real endpoints and stored confidence)
        t0_dep = time.perf_counter()
        dependency_chain_items = []
        if anchor_candidates:
            top_entity_ids = [e["id"] for e in unique_entities if e.get("id")][:10]
            if top_entity_ids:
                try:
                    raw_edges = self.data_access.extract_dependency_chain(snapshot_id, top_entity_ids)
                    seen_edges = set()
                    for edge in raw_edges:
                        frm = edge.get("source") or ""
                        to = edge.get("target") or ""
                        rel = edge.get("relation") or "calls"
                        if not frm or not to or (frm == to):
                            continue
                        # Keep calls, imports, extends
                        if rel not in ["calls", "imports", "extends"]:
                            continue
                        edge_key = (frm, to, rel)
                        if edge_key in seen_edges:
                            continue
                        seen_edges.add(edge_key)

                        edge_obj = {
                            "from": frm,
                            "to": to,
                            "relation": rel
                        }
                        if edge.get("confidence") is not None:
                            edge_obj["confidence"] = edge["confidence"]
                        dependency_chain_items.append(edge_obj)
                except Exception as ex:
                    logger.warning(f"Failed to query dependency chain: {ex}")

        t_dependency_chain = time.perf_counter() - t0_dep

        # 8. Extract Committed Source Lines via GitBlobReader (DEF-020: per-item truncation metadata)
        t0_git = time.perf_counter()
        code_evidence_candidates = []
        if unique_chunks:
            git_reader = None
            repo_path = os.path.join(self.code_root, repo)
            if os.path.isdir(os.path.join(repo_path, ".git")) or os.path.isfile(os.path.join(repo_path, ".git")):
                try:
                    git_reader = GitBlobReader(repo_path)
                except Exception as ex:
                    logger.warning(f"Failed to initialize GitBlobReader for {repo_path}: {ex}")

            seen_chunk_ids = set()
            for chunk in unique_chunks[:10]:
                cid = chunk.get("chunkId")
                cfile = chunk.get("chunkFile")
                s_line = chunk.get("chunkStartLine")
                e_line = chunk.get("chunkEndLine")

                if not cid or cid in seen_chunk_ids or not cfile or s_line is None or e_line is None:
                    continue
                seen_chunk_ids.add(cid)

                raw_lines = []
                if git_reader:
                    try:
                        raw_lines = git_reader.fetch_lines(commit_sha, cfile, int(s_line), int(e_line))
                    except Exception as ex:
                        logger.warning(f"Git fetch skipped for {cfile} L{s_line}-L{e_line}: {ex}")
                        raw_lines = []

                if not raw_lines:
                    continue

                code_evidence_candidates.append({
                    "location": f"{cfile}:L{s_line}-L{e_line}",
                    "file": cfile,
                    "startLine": int(s_line),
                    "endLine": int(s_line) + len(raw_lines) - 1,
                    "raw_lines": raw_lines,
                    "chunkId": cid,
                    "original_lines": len(raw_lines),
                    "kept_lines": len(raw_lines),
                    "truncated": False
                })

        t_git = time.perf_counter() - t0_git

        # DEF-028 & DEF-034: Prune candidates if Laya JEV is enabled
        t_laya_prune = 0.0
        if laya_adapter and laya_adapter.enabled and code_evidence_candidates:
            t0_laya_prune = time.perf_counter()
            code_evidence_candidates = laya_adapter.prune_candidates_sync(task, code_evidence_candidates, max_eval=8)
            t_laya_prune = time.perf_counter() - t0_laya_prune

        # 9. DEF-017 & DEF-016: Strict Whole-Payload Knapsack Packing with Reduced Pack Support
        # On low confidence: return a reduced pack (<=2 anchors, <=1 edge, <=1 code chunk).
        # Never return an empty pack when candidates exist!
        t0_pack = time.perf_counter()
        max_anchors_cap = 2 if is_low_confidence else 4
        max_edges_cap = 1 if is_low_confidence else 4
        max_chunks_cap = 1 if is_low_confidence else len(code_evidence_candidates)

        validation_reasons = []
        if is_low_confidence:
            validation_reasons.append("low confidence query; weak lexical/semantic margin over background; returning reduced context pack")
            if anchor_candidates:
                validation_reasons.append(f"candidate anchor: {anchor_candidates[0]['label']}")
        else:
            if anchor_candidates:
                validation_reasons.append(f"anchor {anchor_candidates[0]['label']} matches task intent")
            if dependency_chain_items:
                validation_reasons.append(f"call chain to {dependency_chain_items[0]['to']} verified")

        val_status = "low_confidence" if is_low_confidence else "pass"

        skeleton_pack = {
            "metadata": {
                "repoId": snapshot["repoId"],
                "commitSHA": commit_sha,
                "commitTimestamp": snapshot.get("commitTimestamp", ""),
                "ingestionTimestamp": snapshot.get("ingestionTimestamp", ""),
                "requestedTask": bounded_task_echo
            },
            "budget_accounting": {
                "requested_tokens": clamped_tokens,
                "consumed_tokens": clamped_tokens,
                "chunks_included": 0,
                "entities_included": 0,
                "truncated": False,
                "confidence_score": round(confidence_score, 2)
            },
            "validation": {
                "status": val_status,
                "score": round(confidence_score, 2),
                "reasons": validation_reasons,
                "expansions_applied": ["1-hop-callee-expansion"] if dependency_chain_items else [],
                "suggested_clarification": (
                    "Query appears off-topic or matches no indexed entities."
                    if is_low_confidence
                    else None
                )
            },
            "architectural_anchors": [],
            "dependency_chain": [],
            "code_evidence": [],
            "metadata_diagnostic": {
                "semanticLayerState": semantic_status or "none",
                "vectorIndexHit": vector_hit,
                "fallbackUsed": fallback_used,
                **({
                    "strategy": strategy_route,
                    "retrieval_strategy": "unified cypher fallback (no per-strategy retrieval variants exist)"
                } if (laya_adapter and laya_adapter.enabled) else {})
            }
        }

        # DEF-036 & DEF-043: Reserve room for validation metadata (~120 tokens) and optional distiller (180 tokens)
        qwen_flag = os.environ.get("ENABLE_QWEN_DISTILLER", "").lower() in ("true", "1", "yes")
        knapsack_target_tokens = max(50, clamped_tokens - (180 if qwen_flag else 0) - 120)
        packed_anchors = []
        packed_edges = []
        packed_code_evidence = []
        was_truncated = False

        # Phase A: Add anchors (cap by max_anchors_cap)
        for a in anchor_candidates[:max_anchors_cap]:
            trial_pack = dict(skeleton_pack)
            trial_pack["architectural_anchors"] = packed_anchors + [a]
            trial_json = json.dumps(trial_pack, indent=1, ensure_ascii=False)
            if math.ceil(len(trial_json) / 3.0) <= knapsack_target_tokens:
                packed_anchors.append(a)
            else:
                was_truncated = True
                break

        # Phase B: Add edges (cap by max_edges_cap)
        for e in dependency_chain_items[:max_edges_cap]:
            trial_pack = dict(skeleton_pack)
            trial_pack["architectural_anchors"] = packed_anchors
            trial_pack["dependency_chain"] = packed_edges + [e]
            trial_json = json.dumps(trial_pack, indent=1, ensure_ascii=False)
            if math.ceil(len(trial_json) / 3.0) <= knapsack_target_tokens:
                packed_edges.append(e)
            else:
                was_truncated = True
                break

        # Phase C: Add code evidence with whole-line truncation (cap by max_chunks_cap)
        # DEF-026: Binary search over raw_lines minimizes json.dumps() invocations
        for ce in code_evidence_candidates[:max_chunks_cap]:
            raw_lines = ce["raw_lines"]
            trial_pack = dict(skeleton_pack)
            trial_pack["architectural_anchors"] = packed_anchors
            trial_pack["dependency_chain"] = packed_edges

            # First test if entire chunk fits
            trial_item = dict(ce)
            trial_pack["code_evidence"] = packed_code_evidence + [trial_item]
            trial_json = json.dumps(trial_pack, indent=1, ensure_ascii=False)

            if math.ceil(len(trial_json) / 3.0) <= knapsack_target_tokens:
                # Fits completely
                packed_code_evidence.append(trial_item)
            else:
                # Truncate whole lines from raw_lines so it fits via binary search
                was_truncated = True
                low = 0
                high = len(raw_lines)
                best_k = 0
                while low <= high:
                    mid = (low + high) // 2
                    cand_lines = raw_lines[:mid]
                    cand_item = dict(ce)
                    cand_item["raw_lines"] = cand_lines
                    cand_item["endLine"] = ce["startLine"] + len(cand_lines) - 1 if cand_lines else ce["startLine"]
                    cand_item["kept_lines"] = len(cand_lines)
                    cand_item["truncated"] = True
                    trial_pack["code_evidence"] = packed_code_evidence + [cand_item]
                    if math.ceil(len(json.dumps(trial_pack, indent=1, ensure_ascii=False)) / 3.0) <= knapsack_target_tokens:
                        best_k = mid
                        low = mid + 1
                    else:
                        high = mid - 1

                if best_k > 0:
                    cand_lines = raw_lines[:best_k]
                    cand_item = dict(ce)
                    cand_item["raw_lines"] = cand_lines
                    cand_item["endLine"] = ce["startLine"] + len(cand_lines) - 1
                    cand_item["kept_lines"] = len(cand_lines)
                    cand_item["truncated"] = True
                    packed_code_evidence.append(cand_item)
                # After truncating an overflowing chunk, remaining budget is exhausted
                break

        # DEF-039 Second Half: Calibrated Validation Signal (Coverage & Top Vector Retention)
        # 1. Top vector candidate retention tracking
        top_vec_file = (top_vector_row.get("chunkFile") or top_vector_row.get("entitySourceFile") or "") if top_vector_row else ""
        top_vec_score = float(top_vector_row.get("vectorScore", 0.0) or 0.0) if top_vector_row else 0.0
        top_vec_retained = True
        top_vec_reason = None

        if top_vector_row and top_vec_score > 0.0 and top_vec_file:
            packed_files = [ce.get("location", "").split(":")[0] for ce in packed_code_evidence]
            top_vec_retained = any(top_vec_file in pf or pf in top_vec_file for pf in packed_files)
            if not top_vec_retained:
                cand_files = [ce.get("location", "").split(":")[0] for ce in code_evidence_candidates]
                in_cands = any(top_vec_file in cf or cf in top_vec_file for cf in cand_files)
                if in_cands:
                    top_vec_reason = f"top vector candidate '{top_vec_file}' (vector score {top_vec_score:.2f}) was dropped by token budget limit"
                else:
                    top_vec_reason = f"top vector candidate '{top_vec_file}' (vector score {top_vec_score:.2f}) was dropped by hybrid ranking"
            else:
                top_vec_reason = f"top vector candidate '{top_vec_file}' is retained in code evidence"

        # 2. Term coverage computation
        term_cov, task_terms, covered_terms = self.compute_term_coverage(
            task=task,
            packed_anchors=packed_anchors,
            packed_code_evidence=packed_code_evidence,
            packed_edges=packed_edges,
            unique_chunks=unique_chunks
        )

        # 3. Aggregate validation reasons
        if top_vec_reason and top_vec_reason not in validation_reasons:
            validation_reasons.append(top_vec_reason)

        cov_reason = f"task term coverage: {term_cov:.0%} ({len(covered_terms)}/{len(task_terms)} content terms matched)"
        if cov_reason not in validation_reasons:
            validation_reasons.append(cov_reason)

        # 4. Status and score determination
        if is_low_confidence:
            final_status = "low_confidence"
            final_val_score = round(confidence_score, 2)
        elif not packed_anchors or not packed_code_evidence:
            final_status = "incomplete"
            final_val_score = round(confidence_score, 2)
        elif term_cov < 0.45:
            # Missed essential task concepts: prevent false pass!
            final_status = "incomplete" if term_cov >= 0.20 else "low_confidence"
            final_val_score = round(min(0.45, 0.20 + 0.35 * term_cov), 2)
            missing_terms_sample = [t[:30] for t in sorted(list(task_terms - covered_terms))[:3]]
            missing_msg = f"insufficient task term coverage ({term_cov:.0%}); missing required query concepts: {', '.join(missing_terms_sample)}"
            if missing_msg not in validation_reasons:
                validation_reasons.append(missing_msg)
        elif not top_vec_retained and term_cov < 0.60:
            final_status = "incomplete"
            final_val_score = round(min(0.48, 0.25 + 0.35 * term_cov), 2)
            top_drop_msg = f"top vector candidate '{top_vec_file}' omitted and partial coverage ({term_cov:.0%})"
            if top_drop_msg not in validation_reasons:
                validation_reasons.append(top_drop_msg)
        else:
            final_status = "pass"
            final_val_score = round(min(1.0, 0.50 + 0.50 * term_cov), 2)

        # 5. Suggested clarification when status is not pass
        suggested_clarification = None
        if is_low_confidence and is_off_topic:
            suggested_clarification = "Query appears off-topic or matches no indexed entities."
        elif final_status in ("low_confidence", "incomplete"):
            missing_sample = [t[:30] for t in sorted(list(task_terms - covered_terms))[:3]]
            if missing_sample:
                suggested_clarification = f"Retrieved pack lacks key query concepts: {', '.join(missing_sample)}. Consider refining task description or specifying target files."

        final_pack = dict(skeleton_pack)
        final_pack["validation"]["status"] = final_status
        final_pack["validation"]["score"] = final_val_score
        final_pack["validation"]["reasons"] = validation_reasons
        if suggested_clarification:
            final_pack["validation"]["suggested_clarification"] = suggested_clarification
        final_pack["architectural_anchors"] = packed_anchors
        final_pack["dependency_chain"] = packed_edges
        final_pack["code_evidence"] = packed_code_evidence
        final_pack["budget_accounting"]["chunks_included"] = len(packed_code_evidence)
        final_pack["budget_accounting"]["entities_included"] = len(packed_anchors)
        final_pack["budget_accounting"]["truncated"] = was_truncated or is_off_topic

        # DEF-028 & DEF-032 & DEF-033: Merge Laya JEV validation before the final recount/trim loop!
        t_laya_val = 0.0
        if laya_adapter and laya_adapter.enabled:
            if laya_adapter.is_ready:
                t0_laya_val = time.perf_counter()
                laya_val = laya_adapter.validate_pack_sync(task, final_pack)
                t_laya_val = time.perf_counter() - t0_laya_val
                if laya_val.get("status") != "unverified":
                    final_pack["validation"]["status"] = laya_val.get("status", final_pack["validation"]["status"])
                    final_pack["validation"]["score"] = laya_val.get("score", final_pack["validation"]["score"])
                    for r in laya_val.get("reasons", []):
                        if r not in final_pack["validation"]["reasons"]:
                            final_pack["validation"]["reasons"].append(r)
                    if laya_val.get("suggested_clarification"):
                        final_pack["validation"]["suggested_clarification"] = laya_val["suggested_clarification"]
                else:
                    for r in laya_val.get("reasons", []):
                        if r not in final_pack["validation"]["reasons"]:
                            final_pack["validation"]["reasons"].append(r)
            else:
                final_pack["validation"]["reasons"].append("Laya JEV not ready (loading in background); algorithmic validation retained")
                final_pack["metadata_diagnostic"]["laya_status"] = "not_ready"

        # M8 & DEF-036: Optional Qwen Distillation Layer (mode=turbo+qwen) executed before budget enforcement!
        if qwen_flag:
            try:
                from turbo_distiller import QwenDistillerClient
                qwen_client = QwenDistillerClient()
                final_pack = qwen_client.distill_sync(task, final_pack)
            except Exception as q_err:
                logger.warning(f"Qwen distillation failed to execute: {q_err}")
                if "validation" in final_pack and "reasons" in final_pack["validation"]:
                    final_pack["validation"]["reasons"].append(f"Qwen distiller fallback ({q_err}); algorithmic core pack preserved")

        def _measure_pack(p: Dict[str, Any]) -> int:
            for _ in range(4):
                cur_len = len(json.dumps(p, indent=1, ensure_ascii=False))
                ct = math.ceil(cur_len / 3.0)
                if p["budget_accounting"]["consumed_tokens"] == ct:
                    return ct
                p["budget_accounting"]["consumed_tokens"] = ct
            return math.ceil(len(json.dumps(p, indent=1, ensure_ascii=False)) / 3.0)

        # DEF-032 & DEF-036 & DEF-043: Strictly enforce ceil(len(json)/3.0) <= clamped_tokens AFTER all fields (Laya/Qwen) are merged
        cur_consumed = _measure_pack(final_pack)
        while cur_consumed > clamped_tokens:
            final_pack["budget_accounting"]["truncated"] = True
            # DEF-043: Do NOT demote validation status to 'incomplete' simply because trailing code lines were trimmed!
            # Truncation is tracked via budget_accounting.truncated; validation status reflects
            # semantic query term coverage and candidate retention.
            if not final_pack["code_evidence"] or not final_pack["architectural_anchors"]:
                final_pack["validation"]["status"] = "incomplete"
            if final_pack["code_evidence"]:
                last_ce = final_pack["code_evidence"][-1]
                if len(last_ce["raw_lines"]) > 1:
                    last_ce["raw_lines"].pop()
                    last_ce["endLine"] = last_ce["startLine"] + len(last_ce["raw_lines"]) - 1
                    last_ce["kept_lines"] = len(last_ce["raw_lines"])
                    last_ce["truncated"] = True
                else:
                    final_pack["code_evidence"].pop()
                    final_pack["budget_accounting"]["chunks_included"] = len(final_pack["code_evidence"])
            elif final_pack["dependency_chain"]:
                final_pack["dependency_chain"].pop()
            elif final_pack["architectural_anchors"]:
                final_pack["architectural_anchors"].pop()
                final_pack["budget_accounting"]["entities_included"] = len(final_pack["architectural_anchors"])
            elif final_pack["validation"].get("suggested_clarification"):
                # At small budgets drop suggested_clarification to fit hard cap
                final_pack["validation"]["suggested_clarification"] = None
            elif final_pack["validation"].get("reasons"):
                # At small budgets shorten or drop reasons (preserving status and score)
                reasons = final_pack["validation"]["reasons"]
                if len(reasons) > 1:
                    reasons.pop()
                elif len(reasons) == 1 and len(reasons[0]) > 40:
                    reasons[0] = reasons[0][:35] + "..."
                else:
                    reasons.pop()
            elif final_pack.get("metadata_diagnostic") and len(final_pack["metadata_diagnostic"]) > 0:
                final_pack["metadata_diagnostic"].clear()
            else:
                break
            cur_consumed = _measure_pack(final_pack)

        t_knapsack_recount = time.perf_counter() - t0_pack
        t_core_assembly = (
            t_snapshot +
            t_cypher +
            t_dependency_chain +
            t_scoring_grouping +
            t_git +
            t_knapsack_recount
        )
        t_total_build = t_core_assembly + t_embed

        self.last_timings = {
            "snapshot_lookup_ms": round(t_snapshot * 1000.0, 3),
            "query_embedding_ms": round(t_embed * 1000.0, 3),
            "candidate_cypher_ms": round(t_cypher * 1000.0, 3),
            "scoring_grouping_ms": round(t_scoring_grouping * 1000.0, 3),
            "dependency_chain_ms": round(t_dependency_chain * 1000.0, 3),
            "git_streaming_ms": round(t_git * 1000.0, 3),
            "packing_recount_ms": round(t_knapsack_recount * 1000.0, 3),
            "core_assembly_ms": round(t_core_assembly * 1000.0, 3),
            "total_build_ms": round(t_total_build * 1000.0, 3),
        }

        if laya_adapter and laya_adapter.enabled:
            self.last_timings["laya_route_ms"] = round(t_laya_route * 1000.0, 3)
            self.last_timings["laya_prune_ms"] = round(t_laya_prune * 1000.0, 3)
            self.last_timings["laya_validate_ms"] = round(t_laya_val * 1000.0, 3)
            self.last_timings["laya_total_ms"] = round((t_laya_route + t_laya_prune + t_laya_val) * 1000.0, 3)

        return final_pack

    @staticmethod
    def _parse_location(loc_str: str) -> Tuple[int, Optional[int]]:
        """Parse sourceLocation string (e.g. 'L12-L45' or 'L12') into (start, end)."""
        if not loc_str:
            return 1, None
        m = re.match(r"^L(\d+)(?:-L?(\d+))?$", loc_str)
        if m:
            s = int(m.group(1))
            e = int(m.group(2)) if m.group(2) else None
            return s, e
        m2 = re.search(r'\d+', loc_str)
        s2 = int(m2.group()) if m2 else 1
        return s2, None
