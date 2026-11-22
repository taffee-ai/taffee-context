"""Integration tests for the Neo4j store. Run with TAFFEE_NEO4J_TEST=1 and NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD set."""
import os
import unittest
import uuid

from taffee_context.storage.contract import SnapshotRef, StageRequest, StructuralEdge, StructuralNode
from taffee_context.storage.neo4j_store import Neo4jStore


def fixture(repo_id: str, commit: str, content_hash: str = "c1") -> StageRequest:
    nodes = [StructuralNode(local_id=f"n{i}", label=f"L{i}", kind="function", source_file="a.py",
                            source_location=f"L{i + 1}") for i in range(3)]
    edges = [StructuralEdge(source="n0", target="n1", relation="calls", confidence="EXTRACTED",
                            source_file="a.py", source_location="L1"),
             StructuralEdge(source="n1", target="n2", relation="calls", confidence="EXTRACTED",
                            source_file="a.py", source_location="L2")]
    return StageRequest(ref=SnapshotRef(repo_id, commit), content_hash=content_hash, artifact_hash="a1",
                        nodes=nodes, edges=edges, metadata={"extractorVersion": "test"})


@unittest.skipUnless(os.environ.get("TAFFEE_NEO4J_TEST") == "1", "set TAFFEE_NEO4J_TEST=1 to run database tests")
class Neo4jStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = Neo4jStore.connect(os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j"),
                                       os.environ["NEO4J_PASSWORD"])
        cls.store.initialize()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.store.close()

    def setUp(self) -> None:
        self.repo = f"py-test-{uuid.uuid4().hex[:10]}"
        self.commit = "a" * 40
        self.ref = SnapshotRef(self.repo, self.commit)

    def test_initialize_is_idempotent(self) -> None:
        self.store.initialize()
        self.store.initialize()

    def test_stage_is_hidden_and_counted(self) -> None:
        self.assertEqual(self.store.stage_snapshot(fixture(self.repo, self.commit)), "created")
        s = self.store.summary(self.ref)
        self.assertIsNotNone(s)
        self.assertTrue(s.staged)
        self.assertFalse(s.ready)
        self.assertEqual((s.nodes, s.edges), (3, 2))
        self.assertEqual((s.declared_nodes, s.declared_edges), (3, 2))
        self.assertEqual(s.content_hash, "c1")

    def test_same_content_is_unchanged(self) -> None:
        self.store.stage_snapshot(fixture(self.repo, self.commit))
        self.assertEqual(self.store.stage_snapshot(fixture(self.repo, self.commit)), "unchanged")

    def test_conflicting_content_is_refused(self) -> None:
        self.store.stage_snapshot(fixture(self.repo, self.commit))
        with self.assertRaisesRegex(ValueError, "Immutable snapshot conflict"):
            self.store.stage_snapshot(fixture(self.repo, self.commit, content_hash="c2"))

    def test_publish_makes_visible_and_is_idempotent(self) -> None:
        self.store.stage_snapshot(fixture(self.repo, self.commit))
        self.store.publish_snapshot(self.ref)
        self.store.publish_snapshot(self.ref)
        s = self.store.summary(self.ref)
        self.assertTrue(s.ready)
        self.assertFalse(s.staged)

    def test_publish_missing_snapshot_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.publish_snapshot(self.ref)

    def test_summary_of_missing_snapshot_is_none(self) -> None:
        self.assertIsNone(self.store.summary(self.ref))


if __name__ == "__main__":
    unittest.main()
