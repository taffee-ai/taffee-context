"""The read path refuses writes at the database server, not only in the code.

Every read runs in a read-only transaction. The server rejects a write inside it, so a query that tries to create or
change data fails even if the caller is buggy. Needs TAFFEE_NEO4J_TEST=1 and NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
"""
import os
import unittest
import uuid

from neo4j.exceptions import ClientError

from taffee_context.storage.neo4j_store import Neo4jStore


@unittest.skipUnless(os.environ.get("TAFFEE_NEO4J_TEST") == "1", "set TAFFEE_NEO4J_TEST=1 to run database tests")
class ReadEnforcementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = Neo4jStore.connect(os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j"),
                                       os.environ["NEO4J_PASSWORD"], read_timeout=15)
        cls.marker = f"ReadProbe{uuid.uuid4().hex[:10]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.store.close()

    def test_a_write_through_the_read_path_is_refused_by_the_server(self) -> None:
        with self.assertRaises(ClientError) as ctx:
            self.store._read(f"CREATE (x:{self.marker} {{p: 1}}) RETURN x.p AS p")
        self.assertIn("read access mode", str(ctx.exception).lower())

    def test_the_refused_write_left_no_data(self) -> None:
        rows = self.store._read(f"MATCH (x:{self.marker}) RETURN count(x) AS n")
        self.assertEqual(rows[0]["n"], 0)


if __name__ == "__main__":
    unittest.main()
