#!/usr/bin/env python3
"""
Unit tests for QwenDistillerClient (test_turbo_distiller.py).
Tests all distillation, evidence immutability, mutual exclusivity,
and fallback paths with zero external model or network dependencies.
"""

import os
import sys
import json
import math
import copy
import unittest
from unittest.mock import patch, MagicMock
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# Ensure module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from turbo_distiller import QwenDistillerClient


class MockQwenServerHandler(BaseHTTPRequestHandler):
    mode = "success"  # "success", "error_500", "malformed", "timeout"
    last_request_payload = None

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            try:
                raw_body = self.rfile.read(content_length).decode("utf-8")
                MockQwenServerHandler.last_request_payload = json.loads(raw_body)
            except Exception:
                MockQwenServerHandler.last_request_payload = None

        if self.mode == "success":
            resp = {
                "text": "Order event handler processes queue events and updates shipment state.",
                "model": "Qwen2.5-Coder-0.5B-Instruct",
                "model_revision": "ea3f2471cf",
                "source_lines_referenced": ["payment.py:L1-L20"]
            }
            body = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.mode == "error_500":
            body = b"Internal Model Error"
            self.send_response(500)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.mode == "malformed":
            body = b"not json { broken"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class TestQwenDistillerClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start local mock HTTP server
        cls.server = HTTPServer(("127.0.0.1", 0), MockQwenServerHandler)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        os.environ.pop("ENABLE_QWEN_DISTILLER", None)
        os.environ.pop("ENABLE_LAYA_JEV", None)
        os.environ["QWEN_ENDPOINT"] = f"http://127.0.0.1:{self.port}/distill"
        os.environ["QWEN_TIMEOUT_S"] = "1.0"
        MockQwenServerHandler.mode = "success"

    def tearDown(self):
        os.environ.pop("ENABLE_QWEN_DISTILLER", None)
        os.environ.pop("ENABLE_LAYA_JEV", None)

    def _sample_pack(self):
        return {
            "metadata": {"repoId": "backend-repo"},
            "architectural_anchors": [{"label": "PaymentHandler"}],
            "code_evidence": [
                {
                    "file": "payment.py",
                    "startLine": 1,
                    "endLine": 20,
                    "lines": ["import queue", "def handle_event(): pass"]
                }
            ],
            "validation": {
                "status": "pass",
                "score": 0.85,
                "reasons": ["anchor matches intent"]
            }
        }

    def test_disabled_by_default(self):
        """When disabled, client makes 0 calls and leaves pack untouched."""
        client = QwenDistillerClient()
        self.assertFalse(client.enabled)
        pack = self._sample_pack()
        orig_pack = copy.deepcopy(pack)
        res = client.distill_sync("process payment", pack)
        self.assertEqual(res, orig_pack)
        self.assertNotIn("derived_summary", res)

    def test_mutual_exclusivity(self):
        """When both Qwen and Laya are enabled, raises ValueError."""
        os.environ["ENABLE_QWEN_DISTILLER"] = "true"
        os.environ["ENABLE_LAYA_JEV"] = "true"
        with self.assertRaises(ValueError) as ctx:
            QwenDistillerClient()
        self.assertIn("mutually exclusive", str(ctx.exception))

    def test_successful_distillation_and_evidence_immutability(self):
        """Successful distillation populates derived_summary without mutating code_evidence."""
        os.environ["ENABLE_QWEN_DISTILLER"] = "true"
        client = QwenDistillerClient()
        pack = self._sample_pack()
        orig_code_evidence = copy.deepcopy(pack["code_evidence"])

        res = client.distill_sync("process payment", pack)
        self.assertIn("derived_summary", res)
        summary = res["derived_summary"]
        self.assertEqual(summary["model"], "Qwen2.5-Coder-0.5B-Instruct")
        self.assertEqual(summary["model_revision"], "ea3f2471cf")
        self.assertIn("Order event handler", summary["text"])
        self.assertEqual(summary["source_lines_referenced"], ["payment.py:L1-L20"])

        # Hard invariant: code_evidence must remain strictly byte-identical!
        self.assertEqual(res["code_evidence"], orig_code_evidence)

    def test_fallback_server_error_500(self):
        """When sidecar returns HTTP 500, gracefully falls back without crashing."""
        os.environ["ENABLE_QWEN_DISTILLER"] = "true"
        MockQwenServerHandler.mode = "error_500"
        client = QwenDistillerClient()
        pack = self._sample_pack()

        res = client.distill_sync("process payment", pack)
        self.assertNotIn("derived_summary", res)
        self.assertIn("Qwen distiller fallback", res["validation"]["reasons"][-1])

    def test_fallback_malformed_reply(self):
        """When sidecar returns non-JSON, gracefully falls back."""
        os.environ["ENABLE_QWEN_DISTILLER"] = "true"
        MockQwenServerHandler.mode = "malformed"
        client = QwenDistillerClient()
        pack = self._sample_pack()

        res = client.distill_sync("process payment", pack)
        self.assertNotIn("derived_summary", res)
        self.assertIn("malformed non-JSON", res["validation"]["reasons"][-1])

    def test_fallback_unreachable_endpoint(self):
        """When sidecar endpoint is down, gracefully falls back."""
        os.environ["ENABLE_QWEN_DISTILLER"] = "true"
        client = QwenDistillerClient(endpoint="http://127.0.0.1:59999/distill")
        pack = self._sample_pack()

        res = client.distill_sync("process payment", pack)
        self.assertNotIn("derived_summary", res)
        self.assertIn("service unreachable", res["validation"]["reasons"][-1])

    def test_real_pack_schema_extracts_raw_lines_code(self):
        """DEF-035: Ensure real pack code_evidence with raw_lines sends non-empty code to sidecar."""
        os.environ["ENABLE_QWEN_DISTILLER"] = "true"
        client = QwenDistillerClient()
        real_pack = {
            "metadata": {
                "repoId": "demo-shop",
                "commitSHA": "1111111111111111111111111111111111111111"
            },
            "architectural_anchors": [{"label": "OrderService"}],
            "code_evidence": [
                {
                    "location": "src/orders/order.service.ts:L37-L45",
                    "file": "src/orders/order.service.ts",
                    "startLine": 37,
                    "endLine": 45,
                    "raw_lines": [
                        "  async handleOrderEvent(event: OrderEvent): Promise<void> {",
                        "    const order = event.payload as Order;",
                        "    await this.markShipped(order.id, 'shipped');",
                        "  }"
                    ],
                    "chunkId": "chunk_ord_001",
                    "original_lines": 4,
                    "kept_lines": 4,
                    "truncated": False
                }
            ],
            "validation": {
                "status": "pass",
                "score": 0.85,
                "reasons": ["anchor matches intent"]
            }
        }
        res = client.distill_sync("process payment webhook", real_pack)
        self.assertIsNotNone(MockQwenServerHandler.last_request_payload)
        payload = MockQwenServerHandler.last_request_payload
        self.assertEqual(payload["task"], "process payment webhook")
        snippets = payload.get("snippets", [])
        self.assertEqual(len(snippets), 1)
        self.assertIn("handleOrderEvent(event: OrderEvent)", snippets[0]["content"])
        self.assertIn("markShipped(order.id, 'shipped')", snippets[0]["content"])
        self.assertEqual(snippets[0]["file"], "src/orders/order.service.ts")
        self.assertIn("derived_summary", res)

    def test_budget_enforcement_with_qwen_distiller_across_budgets(self):
        """DEF-036: Enforce ceil(len(json)/3.0) <= max_tokens across several budgets with distiller enabled."""
        from unittest.mock import MagicMock
        from turbo_builder import ContextPackBuilder
        from turbo_data import TurboDataAccess

        os.environ["ENABLE_QWEN_DISTILLER"] = "true"
        mock_da = MagicMock(spec=TurboDataAccess)
        mock_da.get_snapshot.return_value = {
            "id": "snap_001",
            "repoId": "demo-shop",
            "commitSHA": "1111111111111111111111111111111111111111",
            "commitTimestamp": "2026-10-09T00:00:00Z",
            "ingestionTimestamp": "2026-10-09T00:01:00Z",
            "semanticStatus": "disabled"
        }
        mock_da.query_candidates.return_value = [
            {
                "chunkId": f"chk_{i}",
                "chunkFile": "src/payment.ts",
                "chunkStartLine": i * 20 + 1,
                "chunkEndLine": (i + 1) * 20,
                "entityId": f"ent_{i}",
                "entityLabel": f"PaymentHandler_{i}",
                "entityType": "Class",
                "entityDegree": 10,
                "entitySourceFile": "src/payment.ts",
                "vectorScore": 0.8
            }
            for i in range(5)
        ]
        mock_da.extract_dependency_chain.return_value = [
            {"source": "PaymentHandler_0", "target": "QueueClient", "relation": "calls", "confidence": 0.9}
        ]

        builder = ContextPackBuilder(data_access=mock_da, code_root="/nonexistent")
        with patch("turbo_builder.GitBlobReader") as mock_git_cls:
            mock_git_inst = MagicMock()
            mock_git_inst.fetch_lines.return_value = [
                f"    const line_{j} = do_work_{j}('arg_val_{j}', true, 12345);"
                for j in range(30)
            ]
            mock_git_cls.return_value = mock_git_inst

            for test_budget in [500, 1000, 2000, 4000]:
                pack = builder.build_pack(
                    repo="demo-shop",
                    task="process order queue event",
                    max_tokens=test_budget
                )
                self.assertIn("derived_summary", pack)
                pack_json = json.dumps(pack, indent=1, ensure_ascii=False)
                consumed = math.ceil(len(pack_json) / 3.0)
                self.assertLessEqual(
                    consumed, test_budget,
                    f"Budget violated: consumed {consumed} tokens > budget {test_budget}"
                )
                self.assertEqual(pack["budget_accounting"]["consumed_tokens"], consumed)


if __name__ == "__main__":
    unittest.main()
