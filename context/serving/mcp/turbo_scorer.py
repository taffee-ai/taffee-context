#!/usr/bin/env python3
"""
HybridScorer: Compute hybrid retrieval scores for context items.
Combines vector cosine similarity (0.70), graph centrality / log-degree (0.15),
and lexical query term overlap (0.15).
"""

import os
import re
import math
from typing import Dict, Any, Optional, Set

DEFAULT_W_VEC = 0.70
DEFAULT_W_DEG = 0.15
DEFAULT_W_LEX = 0.15

class HybridScorer:
    def __init__(self,
                 snapshot_data: Optional[Dict[str, Any]] = None,
                 w_vec: Optional[float] = None,
                 w_deg: Optional[float] = None,
                 w_lex: Optional[float] = None):
        """
        Initialize scorer with snapshot or candidate metadata for normalization,
        and configurable scoring weights with environment and argument overrides.
        
        Args:
            snapshot_data: Optional dict with 'maxDegree' (default 50),
                           'entityCount', 'chunkCount'.
            w_vec: Vector similarity weight (default 0.70 or TURBO_W_VEC)
            w_deg: Graph degree weight (default 0.15 or TURBO_W_DEG)
            w_lex: Lexical match weight (default 0.15 or TURBO_W_LEX)
        """
        data = snapshot_data or {}
        max_deg = data.get("maxDegree", 50)
        self.max_degree = max_deg if max_deg > 0 else 1

        # Resolve weights: argument override > environment variable > calibrated default
        if w_vec is not None:
            self.w_vec = float(w_vec)
        elif "TURBO_W_VEC" in os.environ:
            self.w_vec = float(os.environ["TURBO_W_VEC"])
        else:
            self.w_vec = DEFAULT_W_VEC

        if w_deg is not None:
            self.w_deg = float(w_deg)
        elif "TURBO_W_DEG" in os.environ:
            self.w_deg = float(os.environ["TURBO_W_DEG"])
        else:
            self.w_deg = DEFAULT_W_DEG

        if w_lex is not None:
            self.w_lex = float(w_lex)
        elif "TURBO_W_LEX" in os.environ:
            self.w_lex = float(os.environ["TURBO_W_LEX"])
        else:
            self.w_lex = DEFAULT_W_LEX

    def score(self, item: Dict[str, Any], task_query: str) -> float:
        """
        Compute hybrid score for an entity or chunk candidate record.
        
        Default Weights:
            0.70 * vector_similarity + 0.15 * normalized_degree + 0.15 * lexical_overlap
        
        Returns:
            float in range [0.0, 1.0]
        """
        # Component 1: Vector similarity (clamped to [0.0, 1.0])
        v_sim = float(item.get("vectorScore", 0.0) or 0.0)
        v_sim = max(0.0, min(1.0, v_sim))

        # Component 2: Graph centrality (log-normalized degree)
        entity_degree = max(0, int(item.get("entityDegree", 0) or 0))
        denom = math.log(self.max_degree + 1)
        norm_degree = math.log(entity_degree + 1) / denom if denom > 0 else 0.0
        norm_degree = max(0.0, min(1.0, norm_degree))

        # Component 3: Lexical match (term overlap)
        entity_label = str(item.get("entityLabel", "") or "")
        lexical = self._lexical_score(task_query, entity_label)

        # Weighted combination
        final = self.w_vec * v_sim + self.w_deg * norm_degree + self.w_lex * lexical
        return max(0.0, min(1.0, final))

    @staticmethod
    def tokenize(text: str) -> Set[str]:
        """
        Tokenize string into lowercase sub-tokens, splitting on camelCase,
        PascalCase, snake_case, kebab-case, dots, and digits.
        """
        if not text:
            return set()
        # Split transitions from lowercase/digit to uppercase
        s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
        # Split transitions from multi-uppercase to uppercase + lowercase (e.g., SessionToken -> Session Token)
        s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
        # Extract all alphanumeric token sequences
        tokens = set(re.findall(r'[a-zA-Z0-9]+', s.lower()))
        return tokens

    def lexical_score(self, query: str, entity_label: str) -> float:
        """Public alias for _lexical_score."""
        return self._lexical_score(query, entity_label)

    def _lexical_score(self, query: str, entity_label: str) -> float:
        """Compute term overlap score between query and entity label using sub-tokens."""
        query_terms = self.tokenize(query)
        label_terms = self.tokenize(entity_label)
        if not query_terms or not label_terms:
            return 0.0
        overlap = len(query_terms & label_terms)
        max_len = max(len(query_terms), len(label_terms))
        return (overlap / max_len) if max_len > 0 else 0.0
