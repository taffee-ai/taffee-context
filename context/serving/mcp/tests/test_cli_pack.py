#!/usr/bin/env python3
"""
Unit tests for taffee-mcp CLI pack command (Milestone 5).
Tests:
  - CLI argument parsing for 'pack' command (positional task, -r repo, --max-tokens, --commit, --table, --json)
  - pack help / --help output
  - format_table_pack terminal formatting (anchors, dependency chain, evidence summary)
  - format_json_or_table JSON vs Table rendering
"""

import unittest
import json
import io
from contextlib import redirect_stdout, redirect_stderr

from client import build_parser, format_table_pack, format_json_or_table


class TestCliPack(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()
        self.sample_pack = {
            "metadata": {
                "repoId": "demo-shop",
                "commitSHA": "5d3e8c7a9f2b1e4d6c3a8b7e9f2d1c3a12345678",
                "commitTimestamp": "2026-10-08T15:32:14Z",
                "ingestionTimestamp": "2026-10-08T15:45:00Z",
                "requestedTask": "validate widget access"
            },
            "budget_accounting": {
                "requested_tokens": 4000,
                "consumed_tokens": 1250,
                "chunks_included": 2,
                "entities_included": 3,
                "truncated": False,
                "confidence_score": 0.88
            },
            "validation": {
                "status": "pass",
                "score": 0.88,
                "reasons": ["anchor AdminGuard matches task intent"],
                "expansions_applied": ["1-hop-callee-expansion"],
                "suggested_clarification": None
            },
            "architectural_anchors": [
                {
                    "label": "AdminGuard",
                    "type": "class",
                    "location": "src/guards/widget.guard.ts:L12-L45",
                    "file": "src/guards/widget.guard.ts",
                    "startLine": 12,
                    "endLine": 45,
                    "degree": 34,
                    "hybridScore": 0.89
                }
            ],
            "dependency_chain": [
                {
                    "from": "AdminGuard",
                    "to": "validateWidgetAccess",
                    "relation": "calls",
                    "confidence": 0.99
                }
            ],
            "code_evidence": [
                {
                    "location": "src/guards/widget.guard.ts:L12-L30",
                    "file": "src/guards/widget.guard.ts",
                    "startLine": 12,
                    "endLine": 30,
                    "raw_lines": [
                        "export class AdminGuard implements CanActivate {"
                    ],
                    "chunkId": "chk-1234",
                    "tokenCount": 55
                }
            ],
            "metadata_diagnostic": {
                "semanticLayerState": "ready",
                "vectorIndexHit": True,
                "fallbackUsed": False
            }
        }

    def test_pack_cli_parsing(self):
        """Test pack command parsing with options."""
        args = self.parser.parse_args([
            "pack", "check admin guard",
            "-r", "demo-shop",
            "--max-tokens", "2500",
            "--commit", "5d3e8c7a",
            "--table"
        ])
        self.assertEqual(args.command, "pack")
        self.assertEqual(args.task, "check admin guard")
        self.assertEqual(args.repo, "demo-shop")
        self.assertEqual(args.max_tokens, 2500)
        self.assertEqual(args.commit, "5d3e8c7a")
        self.assertEqual(args.format, "table")

    def test_pack_cli_help(self):
        """Test pack help output includes command flags."""
        f = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(f):
            self.parser.parse_args(["pack", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        out = f.getvalue()
        self.assertIn("--max-tokens", out)
        self.assertIn("task", out)
        self.assertIn("--table", out)

    def test_format_table_pack_sections(self):
        """Test table view formats anchors, dependency chain and code evidence."""
        tbl = format_table_pack(self.sample_pack)
        self.assertIsNotNone(tbl)
        self.assertIn("Context Pack: demo-shop @ 5d3e8c7a9f", tbl)
        self.assertIn("=== ARCHITECTURAL ANCHORS ===", tbl)
        self.assertIn("AdminGuard", tbl)
        self.assertIn("=== DEPENDENCY CHAIN ===", tbl)
        self.assertIn("validateWidgetAccess", tbl)
        self.assertIn("=== CODE EVIDENCE SUMMARY ===", tbl)
        self.assertIn("src/guards/widget.guard.ts", tbl)
        self.assertIn("chk-1234", tbl)

    def test_format_json_or_table_json_mode(self):
        """Test format_json_or_table in JSON mode."""
        res = format_json_or_table(self.sample_pack, use_table=False, command_name="pack")
        parsed = json.loads(res)
        self.assertEqual(parsed["metadata"]["repoId"], "demo-shop")
        self.assertEqual(parsed["budget_accounting"]["consumed_tokens"], 1250)

    def test_format_json_or_table_table_mode(self):
        """Test format_json_or_table in table mode."""
        res = format_json_or_table(self.sample_pack, use_table=True, command_name="pack")
        self.assertIn("=== ARCHITECTURAL ANCHORS ===", res)
        self.assertIn("=== DEPENDENCY CHAIN ===", res)
        self.assertIn("=== CODE EVIDENCE SUMMARY ===", res)


if __name__ == "__main__":
    unittest.main()
