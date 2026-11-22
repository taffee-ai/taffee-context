#!/usr/bin/env python3
"""
TokenKnapsack: Deterministic token budget packer for context items.
Uses conservative ceil(len(text) / chars_per_token) estimation with zero
network dependencies or model downloads.

When candidates exceed budget, truncates the overflowing item at line boundaries
(never mid-line) to maximize utilization while guaranteeing consumed <= max_tokens.
"""

import re
import math
from typing import List, Dict, Tuple, Optional, Any

class TokenKnapsack:
    def __init__(self, chars_per_token: float = 3.0):
        """
        Initialize TokenKnapsack with a conservative character-to-token ratio.
        
        Args:
            chars_per_token: Number of characters assumed per token (default 3.0).
        """
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        self.chars_per_token = float(chars_per_token)

    def estimate_tokens(self, text: str) -> int:
        """
        Deterministically estimate token count using conservative ceiling bound.
        
        Returns:
            0 if empty/None, else max(1, math.ceil(len(text) / self.chars_per_token)).
        """
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self.chars_per_token))

    def pack(self,
             sorted_items: List[Dict[str, Any]],
             max_tokens: int,
             priorities: Optional[List[str]] = None) -> Tuple[List[Dict[str, Any]], int, bool]:
        """
        Greedy pack items in priority order without exceeding max_tokens.
        
        If an item exceeds the remaining budget, attempts to truncate whole lines
        from the start of the item (keeping as many whole lines as fit) to fit within
        the remaining budget.
        
        Args:
            sorted_items: Candidates with 'priority', and either 'tokenCount' or 'raw_lines' / 'text'.
            max_tokens: Hard ceiling in tokens.
            priorities: Priority grouping order (default ['anchor', 'edge', 'code']).
            
        Returns:
            (packed_items, consumed_tokens, was_truncated)
        """
        if max_tokens <= 0 or not sorted_items:
            return [], 0, (bool(sorted_items) if max_tokens <= 0 else False)

        prio_order = priorities or ["anchor", "edge", "code"]
        consumed = 0
        packed: List[Dict[str, Any]] = []
        was_truncated = False

        # Group items by priority while preserving internal ordering
        by_priority: Dict[str, List[Dict[str, Any]]] = {p: [] for p in prio_order}
        leftover: List[Dict[str, Any]] = []

        for item in sorted_items:
            prio = item.get("priority", "code")
            if prio in by_priority:
                by_priority[prio].append(item)
            else:
                leftover.append(item)

        all_ordered_groups = [by_priority[p] for p in prio_order]
        if leftover:
            all_ordered_groups.append(leftover)

        for group in all_ordered_groups:
            for item in group:
                raw_lines = item.get("raw_lines")
                if raw_lines is None and "text" in item and item["text"] is not None:
                    raw_lines = re.split(r'\r\n|\r|\n', str(item["text"]))
                    if raw_lines and raw_lines[-1] == '':
                        raw_lines.pop()

                item_tokens = item.get("tokenCount")
                if item_tokens is None:
                    if raw_lines is not None:
                        text_snippet = "\n".join(str(l) for l in raw_lines)
                    else:
                        text_snippet = str(item.get("text", "") or "")
                    item_tokens = self.estimate_tokens(text_snippet)

                item_tokens = max(0, int(item_tokens))
                rem_budget = max_tokens - consumed

                if item_tokens <= rem_budget:
                    # Item fits completely
                    item_to_add = dict(item)
                    item_to_add["tokenCount"] = item_tokens
                    if raw_lines is not None:
                        item_to_add["raw_lines"] = list(raw_lines)
                    packed.append(item_to_add)
                    consumed += item_tokens
                else:
                    # Item overflows remaining budget
                    was_truncated = True
                    if rem_budget > 0 and raw_lines and len(raw_lines) > 0:
                        # Truncate at line boundaries: find maximum lines that fit in rem_budget
                        kept_lines = []
                        last_valid_tokens = 0
                        for line in raw_lines:
                            candidate = kept_lines + [str(line)]
                            cand_tokens = self.estimate_tokens("\n".join(candidate))
                            if cand_tokens <= rem_budget:
                                kept_lines = candidate
                                last_valid_tokens = cand_tokens
                            else:
                                break

                        if kept_lines and last_valid_tokens > 0:
                            trunc_item = dict(item)
                            trunc_item["raw_lines"] = kept_lines
                            trunc_item["tokenCount"] = last_valid_tokens
                            trunc_item["truncated"] = True
                            trunc_item["original_line_count"] = len(raw_lines)
                            trunc_item["kept_line_count"] = len(kept_lines)
                            if "startLine" in trunc_item and isinstance(trunc_item["startLine"], int):
                                trunc_item["endLine"] = trunc_item["startLine"] + len(kept_lines) - 1
                            packed.append(trunc_item)
                            consumed += last_valid_tokens
                    # After overflowing and potentially truncating the last fitting candidate, budget is exhausted
                    return packed, consumed, was_truncated

        return packed, consumed, was_truncated
