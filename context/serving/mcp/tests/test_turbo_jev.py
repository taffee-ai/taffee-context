#!/usr/bin/env python3
"""
Unit tests for LayaJEVAdapter (test_turbo_jev.py).
Uses mocked Router to verify all routing, pruning, validation, and fallback paths.
Pure unit tests with ZERO external model or network dependencies.
"""

import os
import sys
import unittest
import asyncio
from unittest.mock import MagicMock, patch

# Ensure module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from turbo_jev import LayaJEVAdapter


class TestLayaJEVAdapter(unittest.TestCase):
    def setUp(self):
        # Clear relevant env vars
        os.environ.pop("ENABLE_LAYA_JEV", None)
        os.environ.pop("ENABLE_QWEN_DISTILLER", None)
        os.environ["LAYA_AUTO_PRELOAD"] = "false"
        # Default mock find_spec so unit tests with mock Router pass on hosts without laya installed
        self.find_spec_patcher = patch("importlib.util.find_spec", return_value=MagicMock())
        self.mock_find_spec = self.find_spec_patcher.start()

    def tearDown(self):
        self.find_spec_patcher.stop()
        os.environ.pop("ENABLE_LAYA_JEV", None)
        os.environ.pop("ENABLE_QWEN_DISTILLER", None)
        os.environ.pop("LAYA_AUTO_PRELOAD", None)

    def test_disabled_by_default(self):
        """When ENABLE_LAYA_JEV is false/unset, Laya is never imported and memory overhead is 0."""
        adapter = LayaJEVAdapter()
        self.assertFalse(adapter.enabled)
        self.assertFalse(adapter.is_ready)
        self.assertFalse(adapter.ensure_ready_sync())
        self.assertEqual(adapter.route_strategy_sync("trace calls"), "standard")
        
        cands = [{"chunkId": "1", "raw_lines": ["code"]}]
        self.assertEqual(adapter.prune_candidates_sync("trace", cands), cands)
        
        val = adapter.validate_pack_sync("trace", {"validation": {}})
        self.assertEqual(val["status"], "pass")
        self.assertIn("JEV disabled", val["reasons"][0])
        
        # Verify laya was never imported
        self.assertNotIn("laya", sys.modules)

    def test_mutual_exclusivity_raises_error(self):
        """mode=turbo+jev and mode=turbo+qwen are strictly mutually exclusive."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        os.environ["ENABLE_QWEN_DISTILLER"] = "true"
        with self.assertRaises(ValueError) as ctx:
            LayaJEVAdapter()
        self.assertIn("mutually exclusive", str(ctx.exception))

    def test_mock_router_ensure_ready_success(self):
        """Thread-safe lazy loader initializes Router successfully."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        self.assertTrue(adapter.enabled)
        self.assertFalse(adapter.is_ready)

        mock_router = MagicMock()
        with patch.object(adapter, "_sync_init", return_value=mock_router) as mock_init:
            ready = adapter.ensure_ready_sync()
            self.assertTrue(ready)
            self.assertTrue(adapter.is_ready)
            mock_init.assert_called_once()
            
            # Second call is a no-op
            self.assertTrue(adapter.ensure_ready_sync())
            self.assertEqual(mock_init.call_count, 1)

    def test_mock_router_load_failure_fallback(self):
        """If model initialization fails, adapter gracefully flags failure and falls back."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()

        with patch.object(adapter, "_sync_init", side_effect=RuntimeError("weights missing")):
            ready = adapter.ensure_ready_sync()
            self.assertFalse(ready)
            self.assertFalse(adapter.is_ready)
            self.assertTrue(adapter._load_failed)
            
            # Subsequent calls do not attempt to reload
            self.assertFalse(adapter.ensure_ready_sync())

    def test_route_strategy_classification(self):
        """Classifies graph traversal intent into expected categories."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        mock_router = MagicMock()
        mock_router.predict.return_value = {
            "answers": {
                "strategy": {"choice": "call_chain"}
            }
        }

        with patch.object(adapter, "_sync_init", return_value=mock_router):
            adapter.ensure_ready_sync()
            choice = adapter.route_strategy_sync("trace payment webhook calls")
            self.assertEqual(choice, "call_chain")
            mock_router.predict.assert_called_once()

    def test_route_strategy_exception_fallback(self):
        """On predict exception, route_strategy safely falls back to standard."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        mock_router = MagicMock()
        mock_router.predict.side_effect = Exception("prediction timeout")

        with patch.object(adapter, "_sync_init", return_value=mock_router):
            adapter.ensure_ready_sync()
            choice = adapter.route_strategy_sync("trace error")
            self.assertEqual(choice, "standard")

    def test_prune_candidates(self):
        """Prunes low-confidence or non-relevant chunks using predict_batch."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        mock_router = MagicMock()
        mock_router.predict_batch.return_value = [
            {"answers": {"is_relevant": {"noul": 0.95, "low_confidence": False}}},
            {"answers": {"is_relevant": {"noul": 0.40, "low_confidence": False}}},
            {"answers": {"is_relevant": {"noul": 0.90, "low_confidence": True}}},
        ]

        candidates = [
            {"chunkId": "c1", "raw_lines": ["func handlePayment()"]},
            {"chunkId": "c2", "raw_lines": ["func unrelatedUtil()"]},
            {"chunkId": "c3", "raw_lines": ["func uncertain()"]},
        ]

        with patch.object(adapter, "_sync_init", return_value=mock_router):
            adapter.ensure_ready_sync()
            retained = adapter.prune_candidates_sync("payment", candidates, threshold=0.85)
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0]["chunkId"], "c1")

    def test_prune_candidates_all_pruned_failsafe(self):
        """If all candidates are pruned, failsafe retains all candidates."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        mock_router = MagicMock()
        mock_router.predict_batch.return_value = [
            {"answers": {"is_relevant": {"noul": 0.10, "low_confidence": False}}},
            {"answers": {"is_relevant": {"noul": 0.20, "low_confidence": False}}},
        ]

        candidates = [
            {"chunkId": "c1", "raw_lines": ["line 1"]},
            {"chunkId": "c2", "raw_lines": ["line 2"]},
        ]

        with patch.object(adapter, "_sync_init", return_value=mock_router):
            adapter.ensure_ready_sync()
            retained = adapter.prune_candidates_sync("task", candidates, threshold=0.85)
            self.assertEqual(len(retained), 2)  # All retained by failsafe

    def test_prune_candidates_exception_fallback(self):
        """On predict_batch failure, all candidates are safely retained."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        mock_router = MagicMock()
        mock_router.predict_batch.side_effect = RuntimeError("GPU OOM / Batch failure")

        candidates = [{"chunkId": "c1", "raw_lines": ["code"]}]
        with patch.object(adapter, "_sync_init", return_value=mock_router):
            adapter.ensure_ready_sync()
            retained = adapter.prune_candidates_sync("task", candidates)
            self.assertEqual(retained, candidates)

    def test_validate_pack_pass(self):
        """Pack validation with high score returns status='pass'."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        mock_router = MagicMock()
        mock_router.predict.return_value = {
            "answers": {
                "intent_satisfied": {"noul": 0.94}
            }
        }

        pack = {
            "architectural_anchors": [{"label": "PaymentHandler"}],
            "code_evidence": [{"file": "payment.py"}],
            "validation": {"expansions_applied": ["1-hop-callee"]}
        }

        with patch.object(adapter, "_sync_init", return_value=mock_router):
            adapter.ensure_ready_sync()
            val = adapter.validate_pack_sync("process payment", pack)
            self.assertEqual(val["status"], "pass")
            self.assertEqual(val["score"], 0.94)
            self.assertIn("intent verification completed", val["reasons"][0])
            self.assertEqual(val["expansions_applied"], ["1-hop-callee"])

    def test_validate_pack_low_confidence(self):
        """Pack validation with low score returns status='low_confidence'."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        mock_router = MagicMock()
        mock_router.predict.return_value = {
            "answers": {
                "intent_satisfied": {"noul": 0.52}
            }
        }

        pack = {
            "architectural_anchors": [],
            "code_evidence": [],
            "validation": {}
        }

        with patch.object(adapter, "_sync_init", return_value=mock_router):
            adapter.ensure_ready_sync()
            val = adapter.validate_pack_sync("off-topic query", pack)
            self.assertEqual(val["status"], "low_confidence")
            self.assertEqual(val["score"], 0.52)
            self.assertIsNotNone(val["suggested_clarification"])

    def test_validate_pack_unready_fallback(self):
        """When adapter is enabled but unready, validate_pack returns unverified diagnostic."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        val = adapter.validate_pack_sync("task", {"validation": {}})
        self.assertEqual(val["status"], "unverified")
        self.assertEqual(val["score"], 0.5)
        self.assertIn("not ready", val["reasons"][0])

    def test_enhance_pack_integration(self):
        """enhance_pack correctly coordinates routing and validation on top of builder."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        mock_router = MagicMock()
        mock_router.predict.side_effect = [
            # First call for route_strategy
            {"answers": {"strategy": {"choice": "module_contract"}}},
            # Second call for validate_pack
            {"answers": {"intent_satisfied": {"noul": 0.88}}}
        ]

        mock_builder = MagicMock()
        mock_builder.build_pack.return_value = {
            "metadata": {"repoId": "repo1"},
            "architectural_anchors": [{"label": "AuthService"}],
            "code_evidence": [{"file": "auth.py"}],
            "validation": {"status": "pass", "score": 0.85, "reasons": []}
        }

        with patch.object(adapter, "_sync_init", return_value=mock_router):
            adapter.ensure_ready_sync()
            pack = adapter.enhance_pack(mock_builder, "repo1", "authenticate user", max_tokens=4000)
            self.assertEqual(pack["validation"]["status"], "pass")
            self.assertEqual(pack["validation"]["score"], 0.88)
            self.assertEqual(pack["validation"]["strategy_applied"], "module_contract")
            mock_builder.build_pack.assert_called_once_with(repo="repo1", task="authenticate user", max_tokens=4000, commit=None)

    def test_async_adapter_methods(self):
        """Verify async methods execute cleanly in event loop."""
        async def run_async():
            os.environ["ENABLE_LAYA_JEV"] = "true"
            adapter = LayaJEVAdapter()
            mock_router = MagicMock()
            mock_router.predict.return_value = {"answers": {"strategy": {"choice": "dependency_audit"}}}
            
            with patch.object(adapter, "_sync_init", return_value=mock_router):
                ready = await adapter.ensure_ready()
                self.assertTrue(ready)
                strat = await adapter.route_strategy("check imports")
                self.assertEqual(strat, "dependency_audit")

        asyncio.run(run_async())


    def test_package_missing_fast_disable_def031(self):
        """DEF-031: When laya package is missing, adapter disables immediately without slow probe."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        self.mock_find_spec.return_value = None
        adapter = LayaJEVAdapter()
        self.assertFalse(adapter.enabled)
        self.assertTrue(adapter._load_failed)

    def test_builder_tool_level_mutual_exclusivity_def028(self):
        """DEF-028: Mutual exclusivity enforced at ContextPackBuilder tool level."""
        from turbo_builder import ContextPackBuilder
        os.environ["ENABLE_LAYA_JEV"] = "true"
        os.environ["ENABLE_QWEN_DISTILLER"] = "true"
        builder = ContextPackBuilder(data_access=MagicMock())
        with self.assertRaises(ValueError) as ctx:
            builder.build_pack(repo="repo1", task="test task")
        self.assertIn("Mutual exclusivity violation", str(ctx.exception))

    def test_builder_integration_flag_off_def028(self):
        """DEF-028: With flag off, ContextPackBuilder produces plain pack with 0 Laya overhead."""
        from turbo_builder import ContextPackBuilder
        os.environ["ENABLE_LAYA_JEV"] = "false"
        mock_da = MagicMock()
        mock_da.get_snapshot.return_value = {
            "id": "snap1",
            "repoId": "repo1",
            "commitSHA": "abcdef1234567890",
            "semanticStatus": "none"
        }
        mock_da.query_candidates.return_value = []
        builder = ContextPackBuilder(data_access=mock_da)
        pack = builder.build_pack(repo="repo1", task="test task")
        self.assertNotIn("strategy", pack.get("metadata_diagnostic", {}))
        self.assertEqual(pack["validation"]["status"], "low_confidence")

    def test_builder_integration_flag_on_def028(self):
        """DEF-028: With flag on, ContextPackBuilder integrates Laya routing, pruning, and validation."""
        from turbo_builder import ContextPackBuilder
        os.environ["ENABLE_LAYA_JEV"] = "true"
        mock_da = MagicMock()
        mock_da.get_snapshot.return_value = {
            "id": "snap1",
            "repoId": "repo1",
            "commitSHA": "abcdef1234567890",
            "semanticStatus": "none"
        }
        mock_da.query_candidates.return_value = []
        
        mock_router = MagicMock()
        mock_router.predict.side_effect = [
            # route_strategy
            {"answers": {"strategy": {"choice": "call_chain"}}},
            # validate_pack
            {"answers": {"intent_satisfied": {"noul": 0.82}}}
        ]
        
        builder = ContextPackBuilder(data_access=mock_da)
        import turbo_builder
        turbo_builder._laya_adapter_instance = None
        
        with patch("turbo_jev.LayaJEVAdapter._sync_init", return_value=mock_router), \
             patch("importlib.util.find_spec", return_value=MagicMock()):
            # Explicitly preload adapter to ensure ready
            turbo_builder._get_laya_adapter().ensure_ready_sync()
            pack = builder.build_pack(repo="repo1", task="test task")
            self.assertEqual(pack["metadata_diagnostic"]["strategy"], "call_chain")
            self.assertIn("unified cypher fallback", pack["metadata_diagnostic"]["retrieval_strategy"])
            self.assertEqual(pack["validation"]["status"], "pass")
            self.assertEqual(pack["validation"]["score"], 0.82)

    def test_unready_model_nonblocking_def033(self):
        """DEF-033: When model is not yet ready, adapter immediately falls back without blocking."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        # Ensure not ready
        self.assertFalse(adapter.is_ready)
        
        # All calls return immediately with safe defaults
        self.assertEqual(adapter.route_strategy_sync("trace calls"), "standard")
        cands = [{"chunkId": "1", "raw_lines": ["code"]}]
        self.assertEqual(adapter.prune_candidates_sync("trace", cands), cands)
        val = adapter.validate_pack_sync("trace", {"validation": {}})
        self.assertEqual(val["status"], "unverified")
        self.assertIn("not ready", val["reasons"][0])

    def test_prune_candidates_max_eval_limit_def034(self):
        """DEF-034: Prune candidates limits batch predict evaluation to max_eval chunks."""
        os.environ["ENABLE_LAYA_JEV"] = "true"
        adapter = LayaJEVAdapter()
        mock_router = MagicMock()
        mock_router.predict_batch.return_value = [
            {"answers": {"is_relevant": {"noul": 0.95}}} for _ in range(5)
        ]
        with patch.object(adapter, "_sync_init", return_value=mock_router):
            adapter.ensure_ready_sync()
            
            # 20 candidate chunks
            cands = [{"chunkId": str(i), "raw_lines": [f"line {i}"]} for i in range(20)]
            result = adapter.prune_candidates_sync("task", cands, max_eval=5)
            
            # Predict batch called with only 5 requests
            self.assertEqual(mock_router.predict_batch.call_count, 1)
            requests_passed = mock_router.predict_batch.call_args[0][0]
            self.assertEqual(len(requests_passed), 5)
            # Result contains all candidates (5 evaluated + 15 remaining)
            self.assertEqual(len(result), 20)

    def test_hard_token_budget_with_laya_on_def032(self):
        """DEF-032: Hard token budget is strictly preserved when Laya validation is merged."""
        import json
        import math
        from turbo_builder import ContextPackBuilder
        os.environ["ENABLE_LAYA_JEV"] = "true"
        
        mock_da = MagicMock()
        mock_da.get_snapshot.return_value = {
            "id": "snap1",
            "repoId": "repo1",
            "commitSHA": "abcdef1234567890",
            "semanticStatus": "none"
        }
        # Provide plenty of candidate items
        mock_da.query_candidates.return_value = [
            {
                "chunkId": f"c_{i}",
                "chunkFile": f"src/file_{i}.py",
                "chunkStartLine": 1,
                "chunkEndLine": 30,
                "vectorScore": 0.9 - (i * 0.05),
                "entityId": f"e_{i}",
                "entityLabel": f"Class_{i}",
                "entityKind": "class",
                "entitySourceFile": f"src/file_{i}.py",
                "entitySourceLocation": "L1-L30",
                "entityDegree": 5
            }
            for i in range(15)
        ]
        mock_git = MagicMock()
        mock_git.fetch_lines.return_value = [f"def function_{j}(): pass" for j in range(25)]
        
        mock_router = MagicMock()
        mock_router.predict.side_effect = [
            # route_strategy
            {"answers": {"strategy": {"choice": "module_contract"}}},
            # validate_pack with long verbose reasons
            {
                "answers": {
                    "intent_satisfied": {"noul": 0.88},
                    "completeness": {"choice": "complete"}
                }
            }
        ] * 10
        mock_router.predict_batch.return_value = [
            {"answers": {"is_relevant": {"noul": 0.95}}} for _ in range(8)
        ]
        
        import turbo_builder
        turbo_builder._laya_adapter_instance = None
        
        with patch("turbo_jev.LayaJEVAdapter._sync_init", return_value=mock_router), \
             patch("importlib.util.find_spec", return_value=MagicMock()), \
             patch("turbo_git.GitBlobReader.fetch_lines", return_value=[f"def function_{j}(): pass" for j in range(25)]):
            adapter = turbo_builder._get_laya_adapter()
            adapter.ensure_ready_sync()
            
            builder = ContextPackBuilder(data_access=mock_da)
            
            for test_budget in [500, 800, 1500, 2500, 4000]:
                pack = builder.build_pack(repo="repo1", task="implement user billing checkout", max_tokens=test_budget)
                json_str = json.dumps(pack, indent=1, ensure_ascii=False)
                consumed_tokens = math.ceil(len(json_str) / 3.0)
                
                # Check strict inequality: consumed_tokens <= test_budget
                self.assertLessEqual(
                    consumed_tokens, test_budget,
                    f"Budget overshoot: consumed {consumed_tokens} > budget {test_budget}"
                )
                self.assertEqual(pack["budget_accounting"]["consumed_tokens"], consumed_tokens)


if __name__ == "__main__":
    unittest.main()


