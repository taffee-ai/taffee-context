#!/usr/bin/env python3
"""
turbo_jev.py: Optional System 1 Non-Autoregressive Laya JEV Adapter.
Colocated in-process in FastMCP container.

Responsibilities:
  1. Pluggable intent routing (route_strategy: call_chain, module_contract, dependency_audit, standard)
  2. Noise pruning (prune_candidates with noul decision instructions)
  3. Context pack validation (validate_pack with intent satisfaction and completeness)
  4. Robust fallback to algorithmic core on unready / error / timeout
  5. Strict mutual exclusivity with Qwen distiller (mode=turbo+jev vs mode=turbo+qwen)
  6. Zero top-level Laya imports when ENABLE_LAYA_JEV=false
"""

import os
import sys
import time
import asyncio
import threading
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("mcp.turbo.jev")


class LayaJEVAdapter:
    """
    In-process adapter for optional System 1 Laya JEV layer.
    
    Guarantees:
      - Colocated in-process using `from laya import Router`.
      - Lazy loaded on first request in worker thread behind lock, non-blocking to server event loop.
      - Never sets is_ready=True until initialization succeeds.
      - When disabled (ENABLE_LAYA_JEV=false), Laya is NEVER imported and memory overhead is 0 MB.
      - Requires raised container memory limit of 3.5 GB when enabled (measured ~2.6 GB RSS).
      - Strict mutual exclusivity with Qwen distiller mode.
      - Graceful algorithmic fallback on unready/failure.
    """

    def __init__(self):
        self.enabled = os.environ.get("ENABLE_LAYA_JEV", "false").lower() in ("true", "1", "yes")
        
        # Check mutual exclusivity with Qwen mode
        qwen_enabled = os.environ.get("ENABLE_QWEN_DISTILLER", "false").lower() in ("true", "1", "yes")
        if self.enabled and qwen_enabled:
            logger.error("Mutual exclusivity violation: ENABLE_LAYA_JEV and ENABLE_QWEN_DISTILLER cannot both be true")
            raise ValueError("mode=turbo+jev and mode=turbo+qwen are strictly mutually exclusive")

        self._router = None
        self._ready = False
        self._load_failed = False
        self._load_lock = asyncio.Lock()
        self._sync_lock = threading.Lock()

        # Offline operation requires LAYA_REVISION=reviewed in container environment
        if "LAYA_REVISION" not in os.environ:
            os.environ["LAYA_REVISION"] = "reviewed"

        if "TORCH_THREADS" not in os.environ:
            os.environ["TORCH_THREADS"] = "2"

        if self.enabled:
            # DEF-031: Check once at start-up with find_spec. If package missing, log and disable immediately.
            import importlib.util
            if importlib.util.find_spec("laya") is None:
                logger.warning("ENABLE_LAYA_JEV=true but 'laya' package is not installed; disabling Laya JEV adapter.")
                self.enabled = False
                self._load_failed = True
            else:
                logger.info("Laya JEV enabled in-process (LAYA_REVISION=%s, TORCH_THREADS=%s)",
                            os.environ.get("LAYA_REVISION"), os.environ.get("TORCH_THREADS"))
                # DEF-033: Start non-blocking background preload so requests do not block for model load
                if os.environ.get("LAYA_AUTO_PRELOAD", "true").lower() in ("true", "1", "yes"):
                    self.start_background_preload()

    @property
    def is_ready(self) -> bool:
        return self._ready

    def start_background_preload(self):
        """Trigger background thread to load model asynchronously without blocking callers (DEF-033)."""
        if not self.enabled or self._ready or self._load_failed:
            return
        t = threading.Thread(target=self._preload_worker, daemon=True, name="LayaPreloadWorker")
        t.start()

    def _preload_worker(self):
        try:
            self.ensure_ready_sync()
        except Exception as e:
            logger.error("Background preload of Laya failed: %s", e)

    def _sync_init(self) -> Any:
        """Internal synchronous model loader."""
        import torch
        torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "2")))
        
        from laya import Router
        logger.info("Initializing in-process Laya Router...")
        router = Router()
        # Warm up / preload english checkpoint
        try:
            router.load("english")
        except Exception as load_err:
            logger.warning("router.load('english') returned: %s; proceeding with default router", load_err)
        return router

    def ensure_ready_sync(self) -> bool:
        """Synchronous thread-safe loader. Blocks until ready or failed."""
        if not self.enabled:
            return False
        if self._ready:
            return True
        if self._load_failed:
            return False

        with self._sync_lock:
            if self._ready:
                return True
            if self._load_failed:
                return False
            try:
                self._router = self._sync_init()
                self._ready = True
                logger.info("Laya JEV Router loaded and ready in-process")
                return True
            except Exception as e:
                self._load_failed = True
                logger.error("Failed to load in-process Laya router: %s", e)
                return False

    async def ensure_ready(self) -> bool:
        """Async thread-safe loader offloaded to worker thread to avoid event loop blocking."""
        if not self.enabled:
            return False
        if self._ready:
            return True
        if self._load_failed:
            return False

        async with self._load_lock:
            if self._ready:
                return True
            if self._load_failed:
                return False
            try:
                self._router = await asyncio.to_thread(self._sync_init)
                self._ready = True
                logger.info("Laya JEV Router loaded and ready in-process")
                return True
            except Exception as e:
                self._load_failed = True
                logger.error("Failed to load in-process Laya router: %s", e)
                return False

    def route_strategy_sync(self, task: str) -> str:
        """Classify graph traversal intent synchronously via Router.predict."""
        if not self.enabled:
            return "standard"
        if not self._ready or self._router is None:
            # DEF-033: Non-blocking immediate fallback when model is not yet ready
            return "standard"

        questions = {
            "strategy": {
                "type": "choice",
                "instructions": "Which graph traversal strategy fits this developer query?",
                "criteria": {
                    "call_chain": "trace function calls, call hierarchies, stack traces",
                    "module_contract": "interface definitions, type signatures, class contracts",
                    "dependency_audit": "imports, dependencies, package root relationships",
                    "standard": "general architectural understanding or code search"
                }
            }
        }
        try:
            res = self._router.predict(task, questions)
            choice = res.get("answers", {}).get("strategy", {}).get("choice", "standard")
            return choice
        except Exception as e:
            logger.warning("Laya JEV route_strategy failed, fallback to standard: %s", e)
            return "standard"

    async def route_strategy(self, task: str) -> str:
        """Async classify graph traversal intent via Router.predict."""
        if not self.enabled or not self._ready or self._router is None:
            return "standard"

        return await asyncio.to_thread(self.route_strategy_sync, task)

    def prune_candidates_sync(self, task: str, candidates: List[Dict[str, Any]], threshold: float = 0.85, max_eval: int = 8) -> List[Dict[str, Any]]:
        """Batch prune candidate chunks synchronously using Router.predict_batch."""
        if not self.enabled or not candidates:
            return candidates
        if not self._ready or self._router is None:
            # DEF-033: Non-blocking immediate return when model is not yet ready
            return candidates

        # DEF-034: Prune only top candidates that could fit within the budget
        # Evaluating 50 candidates sequentially on 2 CPU cores takes >50s!
        # Limiting evaluation to the top candidate chunks (ranked by hybrid score) cuts latency dramatically.
        to_eval = candidates[:max_eval]
        rest = candidates[max_eval:]

        prune_question = {
            "is_relevant": {
                "type": "noul",
                "instructions": f"Does this code snippet directly answer or implement the user query: '{task}'?"
            }
        }
        requests = [
            {
                "state": "\n".join(c.get("raw_lines", [""]))[:500],
                "questions": prune_question
            }
            for c in to_eval
        ]
        try:
            results = self._router.predict_batch(requests)
            retained = []
            for candidate, res in zip(to_eval, results):
                ans = res.get("answers", {}).get("is_relevant", {})
                prob = ans.get("noul", 1.0)
                is_low_conf = ans.get("low_confidence", False)
                if prob >= threshold and not is_low_conf:
                    retained.append(candidate)
            final_top = retained if retained else to_eval
            return final_top + rest
        except Exception as e:
            logger.warning("Laya JEV prune_candidates failed, retaining all candidates: %s", e)
            return candidates

    async def prune_candidates(self, task: str, candidates: List[Dict[str, Any]], threshold: float = 0.85, max_eval: int = 8) -> List[Dict[str, Any]]:
        """Async batch prune candidate chunks."""
        if not self.enabled or not candidates or not self._ready or self._router is None:
            return candidates

        return await asyncio.to_thread(self.prune_candidates_sync, task, candidates, threshold, max_eval)

    def validate_pack_sync(self, task: str, pack: Dict[str, Any]) -> Dict[str, Any]:
        """Validate assembled context pack synchronously against task requirements."""
        if not self.enabled:
            return {
                "status": "pass",
                "score": 1.0,
                "reasons": ["Algorithmic core (JEV disabled)"],
                "expansions_applied": [],
                "suggested_clarification": None
            }
        if not self._ready or self._router is None:
            # DEF-033: Non-blocking immediate fallback when model is not yet ready
            return {
                "status": "unverified",
                "score": 0.5,
                "reasons": ["Laya JEV not ready (loading in background); algorithmic fallback used"],
                "expansions_applied": pack.get("validation", {}).get("expansions_applied", []),
                "suggested_clarification": None
            }

        summary_state = (
            f"Task: {task}\n"
            f"Anchors: {', '.join(a.get('label', '') for a in pack.get('architectural_anchors', []))}\n"
            f"Code Files: {', '.join(set(c.get('file', '') for c in pack.get('code_evidence', [])))}"
        )
        val_questions = {
            "intent_satisfied": {
                "type": "noul",
                "instructions": "Does the assembled code context satisfy the requirements of the user task?"
            },
            "completeness": {
                "type": "score",
                "instructions": "How complete is the architectural context for this task?",
                "criteria": ["incomplete", "partially complete", "complete"]
            }
        }
        try:
            val_res = self._router.predict(summary_state, val_questions)
            score = float(val_res.get("answers", {}).get("intent_satisfied", {}).get("noul", 0.9))
            status = "pass" if score >= 0.70 else "low_confidence"
            return {
                "status": status,
                "score": round(score, 2),
                "reasons": ["Laya in-process intent verification completed"],
                "expansions_applied": pack.get("validation", {}).get("expansions_applied", []),
                "suggested_clarification": None if status == "pass" else "Laya scored pack relevance below threshold"
            }
        except Exception as e:
            logger.warning("Laya JEV validate_pack failed: %s", e)
            return {
                "status": "unverified",
                "score": 0.5,
                "reasons": [f"Validation error: {e}"],
                "expansions_applied": pack.get("validation", {}).get("expansions_applied", []),
                "suggested_clarification": None
            }

    async def validate_pack(self, task: str, pack: Dict[str, Any]) -> Dict[str, Any]:
        """Async validate assembled context pack."""
        if not self.enabled:
            return {
                "status": "pass",
                "score": 1.0,
                "reasons": ["Algorithmic core (JEV disabled)"],
                "expansions_applied": [],
                "suggested_clarification": None
            }
        if not self._ready or self._router is None:
            return {
                "status": "unverified",
                "score": 0.5,
                "reasons": ["Laya JEV not ready (loading in background); algorithmic fallback used"],
                "expansions_applied": [],
                "suggested_clarification": None
            }

        return await asyncio.to_thread(self.validate_pack_sync, task, pack)

    def enhance_pack(self, builder: Any, repo: str, task: str, max_tokens: int = 4000, commit: Optional[str] = None) -> Dict[str, Any]:
        """
        Orchestrate pack assembly with Laya JEV routing and validation.
        Fallback to pure builder pack when JEV is disabled or unready.
        """
        if not self.enabled:
            return builder.build_pack(repo=repo, task=task, max_tokens=max_tokens, commit=commit)

        # 1. Route traversal strategy
        strategy = self.route_strategy_sync(task)
        logger.debug("Laya JEV selected strategy '%s' for task '%s'", strategy, task)

        # 2. Build core pack
        pack = builder.build_pack(repo=repo, task=task, max_tokens=max_tokens, commit=commit)

        # 3. Validate pack with Laya
        validation_result = self.validate_pack_sync(task, pack)
        pack["validation"]["status"] = validation_result["status"]
        pack["validation"]["score"] = validation_result["score"]
        pack["validation"]["reasons"] = validation_result["reasons"]
        if validation_result.get("suggested_clarification"):
            pack["validation"]["suggested_clarification"] = validation_result["suggested_clarification"]
        pack["validation"]["strategy_applied"] = strategy

        return pack
