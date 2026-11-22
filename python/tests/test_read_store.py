"""Read-path tests: the store's read methods, the read-only view, and the snapshot id format.

Database tests need TAFFEE_NEO4J_TEST=1 and NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD. The read-only and id tests need nothing.
"""
import json
import os
import unittest
import uuid

from taffee_context.storage import NotFound, Ambiguous
from taffee_context.storage.contract import SnapshotRef, StageRequest, StructuralEdge, StructuralNode
from taffee_context.storage.neo4j_store import Neo4jStore, snapshot_id
from taffee_context.storage.read_view import ReadOnlyView

VEC_A = [1.0] + [0.0] * 767
VEC_B = [0.0, 1.0] + [0.0] * 766


class ReadOnlyViewTests(unittest.TestCase):
    def test_view_exposes_reads_and_no_writes(self) -> None:
        view = ReadOnlyView(object())  # the provider is never called here
        for name in ["list_repos_page", "resolve_snapshot", "stats", "find_nodes", "neighbours", "read_graph",
                     "community_members", "shortest_path", "semantic_state", "scoped_chunks", "global_chunks",
                     "chunk_symbols", "file_has_entities", "close"]:
            self.assertTrue(callable(getattr(view, name)), name)
        for name in ["stage_snapshot", "publish_snapshot", "initialize", "summary", "_driver", "driver", "run"]:
            self.assertFalse(hasattr(view, name), f"{name} must not be reachable from the read view")

    def test_snapshot_id_matches_the_typescript_loader(self) -> None:
        self.assertEqual(snapshot_id("demo-shop", "2222222222222222222222222222222222222222"),
                         '["demo-shop","2222222222222222222222222222222222222222"]')


@unittest.skipUnless(os.environ.get("TAFFEE_NEO4J_TEST") == "1", "set TAFFEE_NEO4J_TEST=1 to run database tests")
class ReadStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = Neo4jStore.connect(os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j"),
                                       os.environ["NEO4J_PASSWORD"], read_timeout=15)
        cls.store.initialize()
        cls.view = ReadOnlyView(cls.store)
        cls.repo = f"rt-{uuid.uuid4().hex[:8]}"
        cls.commit = "1234abcd" + "0" * 32
        cls.other = "aa11" + "0" * 36
        cls.other2 = "aa22" + "0" * 36
        cls.staged_repo = f"{cls.repo}-staged"
        cls._stage_and_publish(cls.repo, cls.commit)
        cls._stage_and_publish(cls.repo, cls.other)
        cls._stage_and_publish(cls.repo, cls.other2)
        cls.store.stage_snapshot(_fixture(cls.staged_repo, cls.commit))  # staged only: must stay invisible
        cls._seed_chunks(cls.repo, cls.commit)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.store.close()

    @classmethod
    def _stage_and_publish(cls, repo: str, commit: str) -> None:
        cls.store.stage_snapshot(_fixture(repo, commit))
        cls.store.publish_snapshot(SnapshotRef(repo, commit))

    @classmethod
    def _seed_chunks(cls, repo: str, commit: str) -> None:
        sid = snapshot_id(repo, commit)
        with cls.store._driver.session(database=cls.store._database) as session:
            session.run("MATCH (s:ContextSnapshot {id:$s}) SET s.semanticStatus = 'ready'", s=sid).consume()
            session.run(
                "MATCH (e:ContextEntity {snapshotId:$s, localId:'n1'}) "
                "CREATE (c:ContextChunk {snapshotId:$s, id:'c1', file:'agents/agent.py', startLine:1, endLine:40, "
                "charCount:100, embeddedChars:100, truncated:false, tokenTruncated:false, embedding:$va})"
                "-[:DESCRIBES]->(e)", s=sid, va=VEC_A).consume()
            session.run(
                "MATCH (e:ContextEntity {snapshotId:$s, localId:'n2'}) "
                "CREATE (c:ContextChunk {snapshotId:$s, id:'c2', file:'agents/base.py', startLine:1, endLine:40, "
                "charCount:100, embeddedChars:100, truncated:false, tokenTruncated:false, embedding:$vb})"
                "-[:DESCRIBES]->(e)", s=sid, vb=VEC_B).consume()
            session.run("CALL db.awaitIndexes(60)").consume()

    # snapshot resolution

    def test_newest_ready_snapshot_is_resolved_when_no_commit_is_given(self) -> None:
        self.assertIn(self.view.resolve_snapshot(self.repo), {self.commit, self.other, self.other2})

    def test_commit_prefix_matching_one_snapshot_resolves(self) -> None:
        self.assertEqual(self.view.resolve_snapshot(self.repo, "1234"), self.commit)

    def test_commit_prefix_matching_several_is_ambiguous(self) -> None:
        with self.assertRaisesRegex(Ambiguous, "matches 2 ready snapshots"):
            self.view.resolve_snapshot(self.repo, "aa")

    def test_unknown_repo_is_not_found_with_the_tool_text(self) -> None:
        with self.assertRaisesRegex(NotFound, r"no ready snapshot for repo 'no-such-repo' \(see list_repos\)"):
            self.view.resolve_snapshot("no-such-repo")

    def test_staged_snapshot_is_invisible(self) -> None:
        with self.assertRaises(NotFound):
            self.view.resolve_snapshot(self.staged_repo)
        with self.assertRaisesRegex(NotFound, "no ready snapshot"):
            self.view.find_nodes(self.staged_repo, self.commit, "create_agent")
        with self.assertRaisesRegex(NotFound, "no ready snapshot"):
            self.view.stats(self.staged_repo, self.commit)
        with self.assertRaisesRegex(NotFound, "no ready snapshot"):
            self.view.scoped_chunks(snapshot_id(self.staged_repo, self.commit), VEC_A, 2)

    # repos and stats

    def test_list_repos_counts_the_repo_once_by_default(self) -> None:
        total, rows = self.view.list_repos_page(self.repo, 25, 0, False)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["repo"], self.repo)
        self.assertEqual(rows[0]["commits_available"], 3)

    def test_list_repos_all_commits_lists_every_snapshot(self) -> None:
        total, rows = self.view.list_repos_page(self.repo, 25, 0, True)
        self.assertEqual(total, 3)
        self.assertEqual(len(rows), 3)

    def test_stats_counts_nodes_communities_edges_and_confidence(self) -> None:
        s = self.view.stats(self.repo, self.commit)
        self.assertEqual((s["nodes"]["nodes"], s["nodes"]["communities"]), (3, 2))
        self.assertEqual(sorted((e["confidence"], e["n"]) for e in s["edges"]), [("EXTRACTED", 1), ("INFERRED", 1)])
        self.assertEqual(s["chunks"], 2)

    # nodes, neighbours, graph

    def test_find_nodes_exact_then_suffix(self) -> None:
        exact = self.view.find_nodes(self.repo, self.commit, "create_agent")
        self.assertEqual([r["id"] for r in exact], ["n1"])
        suffix = self.view.find_nodes(self.repo, self.commit, "agent")
        self.assertEqual([r["label"] for r in suffix], ["create_agent"])

    def test_neighbours_report_direction_relation_and_confidence(self) -> None:
        rows = self.view.neighbours(self.repo, self.commit, "n1", None, 200)
        self.assertEqual([(r["rel"], r["outgoing"], r["conf"], r["id"]) for r in rows],
                         [("calls", True, "EXTRACTED", "n2")])
        self.assertEqual(self.view.neighbours(self.repo, self.commit, "n1", "imports", 200), [])

    def test_read_graph_returns_native_order_and_properties(self) -> None:
        g = self.view.read_graph(self.repo, self.commit)
        self.assertEqual(sorted(json.loads(n["p"])["label"] for n in g["nodes"]), ["AgentBase", "create_agent", "helper"])
        self.assertEqual(len(g["edges"]), 2)
        self.assertTrue(all(n["p"] for n in g["nodes"]))

    def test_community_members_are_scoped_to_the_community(self) -> None:
        rows = self.view.community_members(self.repo, self.commit, "1", 500)
        self.assertEqual(sorted(r["label"] for r in rows), ["AgentBase", "create_agent"])

    def test_shortest_path_follows_direction(self) -> None:
        rows = self.view.shortest_path(self.repo, self.commit, "n1", "n3", 5, False)
        self.assertEqual(rows[0]["names"], ["create_agent", "AgentBase", "helper"])
        self.assertEqual(rows[0]["rels"], ["calls", "imports"])
        self.assertEqual(self.view.shortest_path(self.repo, self.commit, "n3", "n1", 5, False), [])
        self.assertEqual(len(self.view.shortest_path(self.repo, self.commit, "n3", "n1", 5, True)), 1)

    def test_file_has_entities(self) -> None:
        self.assertTrue(self.view.file_has_entities(snapshot_id(self.repo, self.commit), "agents/agent.py"))
        self.assertFalse(self.view.file_has_entities(snapshot_id(self.repo, self.commit), "nope.py"))

    # semantic

    def test_semantic_state_is_ready_after_seeding(self) -> None:
        self.assertEqual(self.view.semantic_state(self.repo, self.commit), "ready")

    def test_scoped_chunks_return_the_best_chunk_for_the_snapshot(self) -> None:
        top = self.view.scoped_chunks(snapshot_id(self.repo, self.commit), VEC_A, 2)
        self.assertEqual(top[0]["id"], "c1")
        self.assertEqual(top[0]["file"], "agents/agent.py")
        self.assertEqual(set(top[0]), {"id", "file", "s", "e", "score", "cut", "tcut", "emb", "chars", "snap"})

    def test_global_chunks_only_return_ready_snapshots(self) -> None:
        top = self.view.global_chunks(VEC_A, 5)
        self.assertTrue(any(c["id"] == "c1" for c in top))
        self.assertFalse(any(c["snap"] == snapshot_id(self.staged_repo, self.commit) for c in top))

    def test_chunk_symbols_list_the_described_entities(self) -> None:
        self.assertEqual(self.view.chunk_symbols(snapshot_id(self.repo, self.commit), "c1"), ["create_agent L31"])


def _fixture(repo: str, commit: str) -> StageRequest:
    def props(label: str) -> str:
        return json.dumps({"label": label}, sort_keys=True)

    nodes = [
        StructuralNode(local_id="n1", label="create_agent", kind="function", source_file="agents/agent.py",
                       source_location="L31", community="1", native_order=0, native_properties_json=props("create_agent")),
        StructuralNode(local_id="n2", label="AgentBase", kind="class", source_file="agents/base.py",
                       source_location="L5", community="1", native_order=1, native_properties_json=props("AgentBase")),
        StructuralNode(local_id="n3", label="helper", kind="function", source_file="util.py",
                       source_location="L1", community="2", native_order=2, native_properties_json=props("helper")),
    ]
    edges = [
        StructuralEdge(source="n1", target="n2", relation="calls", confidence="EXTRACTED", source_file="agents/agent.py",
                       source_location="L40", native_order=0, native_properties_json=props("e1")),
        StructuralEdge(source="n2", target="n3", relation="imports", confidence="INFERRED", source_file="agents/base.py",
                       source_location="L6", native_order=1, native_properties_json=props("e2")),
    ]
    return StageRequest(ref=SnapshotRef(repo, commit), content_hash="c1", artifact_hash="a1", nodes=nodes, edges=edges)


if __name__ == "__main__":
    unittest.main()
