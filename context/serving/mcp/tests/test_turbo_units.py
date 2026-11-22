#!/usr/bin/env python3
"""
Unit tests for MCP-Turbo pure modules (Milestone 2):
- turbo_scorer.py (HybridScorer)
- turbo_knapsack.py (TokenKnapsack)
- turbo_git.py (GitBlobReader)

Zero external database or model requirements. Runs in plain Python 3.12.
"""

import os
import sys
import math
import random
import tempfile
import subprocess
import unittest

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from turbo_scorer import HybridScorer
from turbo_knapsack import TokenKnapsack
from turbo_git import GitBlobReader
from turbo_builder import ContextPackBuilder

class TestHybridScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = HybridScorer({"maxDegree": 50})

    def test_scorer_zero_input(self):
        item = {"vectorScore": 0.0, "entityDegree": 0, "entityLabel": ""}
        score = self.scorer.score(item, "validate user authentication")
        self.assertEqual(score, 0.0)

    def test_scorer_maximum_input(self):
        item = {"vectorScore": 1.0, "entityDegree": 50, "entityLabel": "authentication guard"}
        score = self.scorer.score(item, "authentication guard")
        self.assertAlmostEqual(score, 1.0, places=4)

    def test_scorer_weights_sum_to_one(self):
        # 0.70 + 0.15 + 0.15 = 1.0
        v = 1.0
        deg = 1.0  # normalized
        lex = 1.0
        combined = 0.70 * v + 0.15 * deg + 0.15 * lex
        self.assertAlmostEqual(combined, 1.0, places=6)
        self.assertAlmostEqual(self.scorer.w_vec + self.scorer.w_deg + self.scorer.w_lex, 1.0, places=6)

    def test_default_degree_weight_cap(self):
        """Fails if default degree weight goes above 0.25."""
        default_scorer = HybridScorer()
        self.assertEqual(default_scorer.w_vec, 0.70)
        self.assertEqual(default_scorer.w_deg, 0.15)
        self.assertEqual(default_scorer.w_lex, 0.15)
        self.assertLessEqual(
            default_scorer.w_deg,
            0.25,
            f"Default degree weight {default_scorer.w_deg} exceeds safe threshold 0.25"
        )

    def test_scorer_degree_normalization_scale(self):
        scorer_large = HybridScorer({"maxDegree": 500})
        scores = []
        for deg in [1, 10, 50, 100, 500, 1000]:
            item = {"vectorScore": 0.5, "entityDegree": deg, "entityLabel": "test"}
            s = scorer_large.score(item, "test")
            self.assertTrue(0.0 <= s <= 1.0)
            scores.append(s)
        # Verify scores are monotonically non-decreasing with degree
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i + 1], scores[i])

    def test_scorer_bounds_randomized(self):
        rng = random.Random(42)
        for _ in range(500):
            item = {
                "vectorScore": rng.uniform(-1.0, 2.0),
                "entityDegree": rng.randint(-10, 1000),
                "entityLabel": "symbol_" + str(rng.randint(0, 50))
            }
            query = "symbol_" + str(rng.randint(0, 50))
            s = self.scorer.score(item, query)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_scorer_subtoken_lexical_matching_def007(self):
        # DEF-007: Sub-token matching for camelCase, snake_case, PascalCase, dots, digits
        item1 = {"vectorScore": 0.0, "entityDegree": 0, "entityLabel": "OrderService"}
        # "order service" vs OrderService: terms match completely -> lexical=1.0 -> score = 0.15
        s1 = self.scorer.score(item1, "order service")
        self.assertAlmostEqual(s1, 0.15, places=4)

        item2 = {"vectorScore": 0.0, "entityDegree": 0, "entityLabel": "ledger_task_2"}
        s2 = self.scorer.score(item2, "ledger task 2")
        self.assertAlmostEqual(s2, 0.15, places=4)

        item3 = {"vectorScore": 0.0, "entityDegree": 0, "entityLabel": "getSessionToken"}
        s3 = self.scorer.score(item3, "get token")
        # tokens: get, session, token (3 total), query has get, token (2 overlap) -> 2/3 lexical
        self.assertGreater(s3, 0.05)


class TestTokenKnapsack(unittest.TestCase):
    def setUp(self):
        self.knapsack = TokenKnapsack(chars_per_token=3.0)

    def test_token_estimation_ceil_bound(self):
        self.assertEqual(self.knapsack.estimate_tokens(""), 0)
        self.assertEqual(self.knapsack.estimate_tokens("a"), 1)       # ceil(1/3) = 1
        self.assertEqual(self.knapsack.estimate_tokens("abc"), 1)     # ceil(3/3) = 1
        self.assertEqual(self.knapsack.estimate_tokens("abcd"), 2)    # ceil(4/3) = 2
        self.assertEqual(self.knapsack.estimate_tokens("abcdef"), 2)  # ceil(6/3) = 2
        self.assertEqual(self.knapsack.estimate_tokens("abcdefg"), 3) # ceil(7/3) = 3

    def test_packer_empty_input(self):
        packed, consumed, truncated = self.knapsack.pack([], max_tokens=1000)
        self.assertEqual(packed, [])
        self.assertEqual(consumed, 0)
        self.assertFalse(truncated)

    def test_packer_exact_fit(self):
        items = [
            {"id": "c1", "tokenCount": 20, "priority": "code"},
            {"id": "c2", "tokenCount": 30, "priority": "code"},
            {"id": "c3", "tokenCount": 50, "priority": "code"},
        ]
        packed, consumed, truncated = self.knapsack.pack(items, max_tokens=100)
        self.assertEqual(len(packed), 3)
        self.assertEqual(consumed, 100)
        self.assertFalse(truncated)

    def test_packer_overflow_and_truncation_without_lines(self):
        # Synthetic items without raw_lines only skip
        items = [
            {"id": "c1", "tokenCount": 40, "priority": "code"},
            {"id": "c2", "tokenCount": 40, "priority": "code"},
            {"id": "c3", "tokenCount": 40, "priority": "code"},
        ]
        packed, consumed, truncated = self.knapsack.pack(items, max_tokens=100)
        self.assertEqual(len(packed), 2)
        self.assertEqual(consumed, 80)
        self.assertTrue(truncated)

    def test_packer_oversize_chunk_line_level_truncation_def008(self):
        # DEF-008: 2000-token chunk packed with budget 1000 must truncate lines and return 1 item
        # 150 lines, each 40 chars = 6000 chars = 2000 tokens
        lines_2000 = [f"const line_{i:03d} = 'something_important_here';" for i in range(150)]
        item = {
            "id": "huge_chunk",
            "raw_lines": lines_2000,
            "startLine": 1,
            "priority": "code"
        }
        packed, consumed, truncated = self.knapsack.pack([item], max_tokens=1000)
        self.assertEqual(len(packed), 1, "Expected 1 truncated item in budget")
        self.assertTrue(truncated, "Expected truncated flag to be True")
        self.assertLessEqual(consumed, 1000, "Consumed tokens must not exceed budget")
        self.assertGreater(consumed, 900, "Should utilize budget near the 1000 token cap")
        
        trunc_item = packed[0]
        self.assertTrue(trunc_item.get("truncated"))
        self.assertEqual(trunc_item["original_line_count"], 150)
        self.assertLess(trunc_item["kept_line_count"], 150)
        self.assertEqual(len(trunc_item["raw_lines"]), trunc_item["kept_line_count"])
        self.assertEqual(trunc_item["endLine"], trunc_item["kept_line_count"])

    def test_packer_multi_item_with_last_item_truncated_def008(self):
        # Item 1 fits in full (300 tokens); Item 2 (1500 tokens) truncates to remaining 700 tokens
        item1 = {
            "id": "item1",
            "tokenCount": 300,
            "priority": "anchor"
        }
        item2_lines = [f"line {i:03d}: function test() {{ return {i}; }}" for i in range(120)]
        item2 = {
            "id": "item2",
            "raw_lines": item2_lines,
            "startLine": 10,
            "priority": "code"
        }
        packed, consumed, truncated = self.knapsack.pack([item1, item2], max_tokens=1000)
        self.assertEqual(len(packed), 2)
        self.assertTrue(truncated)
        self.assertLessEqual(consumed, 1000)
        self.assertGreater(consumed, 950)
        self.assertEqual(packed[0]["id"], "item1")
        self.assertEqual(packed[1]["id"], "item2")
        self.assertTrue(packed[1]["truncated"])

    def test_packer_single_line_larger_than_budget(self):
        # A single line that alone exceeds the remaining budget cannot be truncated mid-line
        item = {
            "id": "giant_line",
            "raw_lines": ["x" * 3000],  # 1000 tokens in 1 line
            "priority": "code"
        }
        packed, consumed, truncated = self.knapsack.pack([item], max_tokens=100)
        self.assertEqual(packed, [])
        self.assertEqual(consumed, 0)
        self.assertTrue(truncated)

    def test_packer_priority_ordering(self):
        # Anchor must be packed first, then edge, then code
        items = [
            {"id": "code1", "tokenCount": 40, "priority": "code"},
            {"id": "edge1", "tokenCount": 30, "priority": "edge"},
            {"id": "anchor1", "tokenCount": 30, "priority": "anchor"},
        ]
        packed, consumed, truncated = self.knapsack.pack(items, max_tokens=70)
        self.assertEqual(len(packed), 2)
        self.assertEqual([p["id"] for p in packed], ["anchor1", "edge1"])
        self.assertEqual(consumed, 60)
        self.assertTrue(truncated)

    def test_packer_seeded_randomized_1000_cases(self):
        rng = random.Random(1337)
        for case in range(1000):
            num_items = rng.randint(1, 30)
            max_tokens = rng.randint(10, 2000)
            items = []
            for i in range(num_items):
                prio = rng.choice(["anchor", "edge", "code"])
                # Mix of synthetic token counts and raw_lines
                if rng.random() < 0.5:
                    tokens = rng.randint(1, 150)
                    items.append({
                        "id": f"item_{case}_{i}",
                        "tokenCount": tokens,
                        "priority": prio
                    })
                else:
                    lines = [f"line_{l}: var x = {rng.randint(0, 1000)};" for l in range(rng.randint(1, 50))]
                    items.append({
                        "id": f"item_{case}_{i}",
                        "raw_lines": lines,
                        "startLine": 1,
                        "priority": prio
                    })

            packed, consumed, truncated = self.knapsack.pack(items, max_tokens=max_tokens)

            # Invariant 1: consumed tokens must never exceed max_tokens
            self.assertLessEqual(consumed, max_tokens, f"Case {case} exceeded budget: {consumed} > {max_tokens}")

            # Invariant 2: sum of packed tokens matches consumed
            sum_tokens = sum(p["tokenCount"] for p in packed)
            self.assertEqual(consumed, sum_tokens, f"Case {case} token count mismatch")


class TestGitBlobReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.repo_path = cls.temp_dir.name

        # Initialize temporary Git repository
        subprocess.run(["git", "init", cls.repo_path], check=True, capture_output=True)
        subprocess.run(["git", "-C", cls.repo_path, "config", "user.name", "Test Runner"], check=True)
        subprocess.run(["git", "-C", cls.repo_path, "config", "user.email", "test@example.com"], check=True)

        # File 1: standard source file with 10 lines
        f1_path = os.path.join(cls.repo_path, "auth.ts")
        cls.auth_lines = [f"line {i}: export const auth_{i} = () => {{}};" for i in range(1, 11)]
        with open(f1_path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(cls.auth_lines) + "\n")

        # File 2: filename containing shell metacharacters (; $ & | " ')
        weird_name = "evil;$(rm -rf);&|file.ts"
        f2_path = os.path.join(cls.repo_path, weird_name)
        cls.weird_lines = ["line 1 in weird file", "line 2 in weird file"]
        with open(f2_path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(cls.weird_lines) + "\n")

        # File 3: DEF-009 test file with \f, \u2028, CRLF, lone CR, and trailing newline
        f3_path = os.path.join(cls.repo_path, "special_lines.ts")
        # Line 1: has \f
        # Line 2: has \u2028
        # Line 3: ended with \r\n
        # Line 4: ended with \r
        # Line 5: ended with \n
        cls.special_expected = [
            "line 1 with formfeed \x0c inside",
            "line 2 with line_sep \u2028 inside",
            "line 3 after crlf",
            "line 4 after lone cr",
            "line 5 trailing"
        ]
        special_content = (
            cls.special_expected[0] + "\r\n" +
            cls.special_expected[1] + "\r" +
            cls.special_expected[2] + "\r\n" +
            cls.special_expected[3] + "\n" +
            cls.special_expected[4] + "\n"
        )
        with open(f3_path, "w", encoding="utf-8", newline="") as fp:
            fp.write(special_content)

        # Commit files
        subprocess.run(["git", "-C", cls.repo_path, "add", "auth.ts", weird_name, "special_lines.ts"], check=True)
        subprocess.run(["git", "-C", cls.repo_path, "commit", "-m", "initial commit"], check=True, capture_output=True)

        rev_cp = subprocess.run(["git", "-C", cls.repo_path, "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        cls.head_commit = rev_cp.stdout.strip()
        cls.weird_name = weird_name

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        self.reader = GitBlobReader(self.repo_path)

    def test_fetch_valid_line_ranges(self):
        lines = self.reader.fetch_lines(self.head_commit, "auth.ts", start_line=1, end_line=5)
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines, self.auth_lines[0:5])

        lines_mid = self.reader.fetch_lines(self.head_commit, "auth.ts", start_line=4, end_line=6)
        self.assertEqual(len(lines_mid), 3)
        self.assertEqual(lines_mid, self.auth_lines[3:6])

        # Clamped past end
        lines_past = self.reader.fetch_lines(self.head_commit, "auth.ts", start_line=8, end_line=20)
        self.assertEqual(len(lines_past), 3)
        self.assertEqual(lines_past, self.auth_lines[7:10])

    def test_invalid_commit_format_rejected(self):
        for bad in ["HEAD", "master", "1234", "not-a-sha-at-all", "1a2b3c4d", ""]:
            with self.assertRaises(ValueError):
                self.reader.fetch_lines(bad, "auth.ts", 1, 5)

    def test_missing_commit_or_missing_file_returns_empty(self):
        fake_sha = "0000000000000000000000000000000000000000"
        self.assertEqual(self.reader.fetch_lines(fake_sha, "auth.ts", 1, 5), [])
        self.assertEqual(self.reader.fetch_lines(self.head_commit, "nonexistent.ts", 1, 5), [])

    def test_path_traversal_refused(self):
        for bad_path in ["../outside.ts", "/etc/passwd", "src/../../secret.txt", "\\windows\\win.ini"]:
            with self.assertRaises(ValueError):
                self.reader.fetch_lines(self.head_commit, bad_path, 1, 5)

    def test_shell_metacharacters_handled_as_plain_text(self):
        lines = self.reader.fetch_lines(self.head_commit, self.weird_name, 1, 2)
        self.assertEqual(lines, self.weird_lines)

    def test_line_splitting_parity_chunker_def009(self):
        # DEF-009: splitLines parity with chunker.ts
        # Must return exactly 5 lines without splitting on \f or \u2028, and dropping trailing empty
        lines = self.reader.fetch_lines(self.head_commit, "special_lines.ts", start_line=1, end_line=5)
        self.assertEqual(len(lines), 5, f"Expected exactly 5 lines, got {len(lines)}: {lines}")
        self.assertEqual(lines, self.special_expected)


class TestDeterminism100Repeats(unittest.TestCase):
    def test_scorer_determinism_100_repeats(self):
        scorer = HybridScorer({"maxDegree": 50})
        item = {"vectorScore": 0.812345, "entityDegree": 17, "entityLabel": "SessionAuthGuard"}
        query = "session auth guard check"
        first = scorer.score(item, query)
        for _ in range(100):
            self.assertEqual(scorer.score(item, query), first)

    def test_knapsack_determinism_100_repeats(self):
        knapsack = TokenKnapsack(chars_per_token=3.0)
        items = [
            {"id": f"item_{i}", "tokenCount": (i * 17) % 50 + 5, "priority": "code" if i % 2 == 0 else "anchor"}
            for i in range(20)
        ]
        first_packed, first_consumed, first_trunc = knapsack.pack(items, max_tokens=250)
        for _ in range(100):
            p, c, t = knapsack.pack(items, max_tokens=250)
            self.assertEqual(c, first_consumed)
            self.assertEqual(t, first_trunc)
            self.assertEqual([x["id"] for x in p], [x["id"] for x in first_packed])


class TestCandidatePoolScaling(unittest.TestCase):
    def test_adaptive_pool_scaling(self):
        """Fails if candidate pool stops scaling with chunk count or violates bounds."""
        # Baseline target repositories
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(263), 50)
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(1000), 100)
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(2598), 200)

        # Clamping bounds: [50, 200]
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(0), 50)
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(10), 50)
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(500), 50)
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(2000), 200)
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(10000), 200)
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(None), 50)

        # Monotonic scaling verification
        prev_pool = 50
        for cnt in range(500, 2001, 100):
            pool = ContextPackBuilder.compute_candidate_pool(cnt)
            self.assertGreaterEqual(pool, prev_pool, f"Candidate pool decreased from {prev_pool} to {pool} at chunk {cnt}")
            prev_pool = pool

    def test_candidate_pool_overrides(self):
        # Explicit argument override
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(263, override=150), 150)
        self.assertEqual(ContextPackBuilder.compute_candidate_pool(2598, override=25), 25)

        # Environment variable override
        old_env = os.environ.get("TURBO_CANDIDATE_POOL")
        try:
            os.environ["TURBO_CANDIDATE_POOL"] = "175"
            self.assertEqual(ContextPackBuilder.compute_candidate_pool(263), 175)
            self.assertEqual(ContextPackBuilder.compute_candidate_pool(2598), 175)
        finally:
            if old_env is not None:
                os.environ["TURBO_CANDIDATE_POOL"] = old_env
            else:
                os.environ.pop("TURBO_CANDIDATE_POOL", None)


class TestValidationSignal(unittest.TestCase):
    """DEF-039 Second Half: Validation Signal calibration and coverage unit tests."""

    def test_task_terms_extraction_filtering(self):
        task = "Which file implements the throttle gate for incoming requests, and which file defines the leaky pail refill policy for the main application? Give the file paths."
        terms = ContextPackBuilder.extract_task_terms(task)
        # Should contain key domain terms
        self.assertIn("pail", terms)
        self.assertIn("throttle", terms)
        self.assertIn("gate", terms)
        self.assertIn("refill", terms)
        # Should filter out stop words and question boilerplate
        self.assertNotIn("which", terms)
        self.assertNotIn("the", terms)
        self.assertNotIn("for", terms)
        self.assertNotIn("file", terms)
        self.assertNotIn("paths", terms)
        self.assertNotIn("give", terms)

    def test_compute_term_coverage_full_coverage(self):
        task = "Find the ThrottleGate implementation"
        anchors = [{"label": "ThrottleGate", "sourceFile": "src/gates/throttle.gate.ts"}]
        code_ev = [{"location": "src/gates/throttle.gate.ts:L1-L30", "file": "src/gates/throttle.gate.ts", "raw_lines": ["export class ThrottleGate implements RateCheck { // implementation\n}"]}]
        cov, task_terms, covered = ContextPackBuilder.compute_term_coverage(task, anchors, code_ev)
        self.assertEqual(cov, 1.0)
        self.assertTrue(task_terms.issubset(covered))

    def test_compute_term_coverage_zero_coverage(self):
        task = "Where is the shipping label printer?"
        anchors = [{"label": "CustomerModule", "sourceFile": "src/customer/customer.module.ts"}]
        code_ev = [{"location": "src/customer/customer.service.ts:L1-L20", "file": "src/customer/customer.service.ts", "raw_lines": ["export class CustomerService {}"]}]
        cov, task_terms, covered = ContextPackBuilder.compute_term_coverage(task, anchors, code_ev)
        self.assertEqual(cov, 0.0)
        self.assertEqual(len(covered), 0)

    def test_compute_term_coverage_partial_miss(self):
        # Multi-concept question where only 1 of 2 concepts is covered
        task = "Which gate implements throttle checks, and which policy defines bucket refill?"
        # Only the throttle gate is packed; the bucket refill policy is completely omitted
        anchors = [{"label": "ThrottleGate", "sourceFile": "src/gates/throttle.gate.ts"}]
        code_ev = [{"location": "src/gates/throttle.gate.ts:L1-L25", "file": "src/gates/throttle.gate.ts", "raw_lines": ["export class ThrottleGate { checkThrottle() {} }"]}]
        cov, task_terms, covered = ContextPackBuilder.compute_term_coverage(task, anchors, code_ev)
        # Should be below 0.45 threshold
        self.assertLess(cov, 0.45)
        self.assertIn("bucket", task_terms - covered)
        self.assertIn("refill", task_terms - covered)

    def test_build_pack_missed_terms_not_pass(self):
        """Simulate builder behavior when pack lacks key task concepts: status must NOT be pass."""
        class MockDataAccess:
            def get_snapshot(self, repo, commit):
                return {"id": "snap-1", "repoId": repo, "commitSHA": "abc1234", "chunkCount": 100}
            def query_candidates(self, snapshot_id, query_vector, task_query, semantic_ready, limit):
                # Return candidates that don't match the query concepts
                return [
                    {
                        "chunkId": "c1",
                        "chunkFile": "src/misc/unrelated.ts",
                        "chunkStartLine": 1,
                        "chunkEndLine": 20,
                        "vectorScore": 0.35,
                        "entityDegree": 2,
                        "entityLabel": "UnrelatedHelper",
                        "entitySourceFile": "src/misc/unrelated.ts",
                        "entitySourceLocation": "L1"
                    }
                ]
            def extract_dependency_chain(self, snapshot_id, entity_ids):
                return []

        builder = ContextPackBuilder(data_access=MockDataAccess(), code_root="/repos")
        pack = builder.build_pack(
            repo="test-repo",
            task="Which controller handles pager integration channels?",
            max_tokens=4000
        )
        val = pack["validation"]
        self.assertNotEqual(val["status"], "pass", f"Missed concepts must not pass! Got {val['status']}")
        self.assertIn(val["status"], ("incomplete", "low_confidence"))
        self.assertLess(val["score"], 0.50)
        # Reason should mention insufficient coverage
        self.assertTrue(any("coverage" in r.lower() for r in val["reasons"]))

    def test_top_vector_drop_reason_reporting(self):
        """Verify that dropping the top vector candidate reports the reason correctly."""
        class MockDataAccessBudgetDrop:
            def get_snapshot(self, repo, commit):
                return {"id": "snap-2", "repoId": repo, "commitSHA": "abc1234", "chunkCount": 100}
            def query_candidates(self, snapshot_id, query_vector, task_query, semantic_ready, limit):
                # Return 2 candidates: top vector candidate with huge lines that will overflow small budget
                return [
                    {
                        "chunkId": "c_huge",
                        "chunkFile": "src/gates/leaky.pail.ts",
                        "chunkStartLine": 1,
                        "chunkEndLine": 500,
                        "vectorScore": 0.95,
                        "entityDegree": 5,
                        "entityLabel": "LeakyPail",
                        "entitySourceFile": "src/gates/leaky.pail.ts",
                        "entitySourceLocation": "L1"
                    },
                    {
                        "chunkId": "c_small",
                        "chunkFile": "src/gates/throttle.gate.ts",
                        "chunkStartLine": 1,
                        "chunkEndLine": 5,
                        "vectorScore": 0.60,
                        "entityDegree": 20,
                        "entityLabel": "ThrottleGate",
                        "entitySourceFile": "src/gates/throttle.gate.ts",
                        "entitySourceLocation": "L1"
                    }
                ]
            def extract_dependency_chain(self, snapshot_id, entity_ids):
                return []

        builder = ContextPackBuilder(
            data_access=MockDataAccessBudgetDrop(),
            code_root="/repos",
            embed_fn=lambda q: [0.1] * 384
        )
        pack = builder.build_pack(
            repo="test-repo",
            task="Find SessionStrategy and ThrottleGate",
            max_tokens=250  # tiny budget forcing drops
        )
        val = pack["validation"]
        # Reasons must state whether top vector candidate was retained or dropped
        reasons_text = " ".join(val["reasons"])
        self.assertTrue(
            "top vector candidate" in reasons_text,
            f"Expected top vector candidate mention in reasons: {val['reasons']}"
        )

    def test_suggested_clarification_on_insufficient_coverage(self):
        """When pack lacks key concepts, suggested_clarification suggests missing terms."""
        class MockDataAccessMiss:
            def get_snapshot(self, repo, commit):
                return {"id": "snap-3", "repoId": repo, "commitSHA": "abc1234", "chunkCount": 100}
            def query_candidates(self, snapshot_id, query_vector, task_query, semantic_ready, limit):
                return [
                    {
                        "chunkId": "c1",
                        "chunkFile": "src/pager/pager.service.ts",
                        "chunkStartLine": 1,
                        "chunkEndLine": 10,
                        "vectorScore": 0.80,
                        "entityDegree": 2,
                        "entityLabel": "PagerService",
                        "entitySourceFile": "src/pager/pager.service.ts",
                        "entitySourceLocation": "L1"
                    }
                ]
            def extract_dependency_chain(self, snapshot_id, entity_ids):
                return []

        builder = ContextPackBuilder(data_access=MockDataAccessMiss(), code_root="/repos")
        pack = builder.build_pack(
            repo="test-repo",
            task="Which controller endpoint returns available pager channels?",
            max_tokens=4000
        )
        val = pack["validation"]
        self.assertIsNotNone(val.get("suggested_clarification"))
        clarification = val["suggested_clarification"].lower()
        self.assertTrue(
            any(k in clarification for k in ["pager", "channels", "endpoint", "controller"]),
            f"Expected missing concepts mentioned in clarification: {val['suggested_clarification']}"
        )

    def test_top_vector_drop_due_to_hybrid_ranking(self):
        """When top vector candidate is omitted from knapsack candidates, reasons state dropped by hybrid ranking."""
        class MockDataAccessHybridDrop:
            def get_snapshot(self, repo, commit):
                return {"id": "snap-4", "repoId": repo, "commitSHA": "abc1234", "chunkCount": 100}
            def query_candidates(self, snapshot_id, query_vector, task_query, semantic_ready, limit):
                # c_top_vec has high vector score but 0 degree and no lexical match,
                # while other items with high degree/lexical outrank it
                return [
                    {
                        "chunkId": "c_hub",
                        "chunkFile": "src/core/hub.ts",
                        "chunkStartLine": 1,
                        "chunkEndLine": 5,
                        "vectorScore": 0.50,
                        "entityDegree": 100,
                        "entityLabel": "CoreHub",
                        "entitySourceFile": "src/core/hub.ts",
                        "entitySourceLocation": "L1"
                    },
                    {
                        "chunkId": "c_vector_best",
                        "chunkFile": "src/core/vector_best.ts",
                        "chunkStartLine": 1,
                        "chunkEndLine": 5,
                        "vectorScore": 0.99,
                        "entityDegree": 0,
                        "entityLabel": "VectorBest",
                        "entitySourceFile": "src/core/vector_best.ts",
                        "entitySourceLocation": "L1"
                    }
                ]
            def extract_dependency_chain(self, snapshot_id, entity_ids):
                return []

        builder = ContextPackBuilder(
            data_access=MockDataAccessHybridDrop(),
            code_root="/repos",
            embed_fn=lambda q: [0.1] * 384
        )
        pack = builder.build_pack(
            repo="test-repo",
            task="Find CoreHub",
            max_tokens=4000
        )
        val = pack["validation"]
        reasons_str = " ".join(val["reasons"])
        self.assertTrue(
            "top vector candidate" in reasons_str,
            f"Expected top vector candidate reporting in reasons: {val['reasons']}"
        )


if __name__ == "__main__":
    unittest.main()


