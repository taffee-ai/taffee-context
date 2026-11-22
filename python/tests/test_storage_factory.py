"""Provider selection. No database needed."""
import unittest

from taffee_context.storage import PROVIDERS, open_store


class StorageFactoryTests(unittest.TestCase):
    def test_neo4j_is_registered(self) -> None:
        self.assertIn("neo4j", PROVIDERS)

    def test_unknown_provider_is_refused_with_the_supported_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown graph database provider 'falkor'; supported: neo4j"):
            open_store("falkor", env={})

    def test_default_provider_is_neo4j(self) -> None:
        with self.assertRaisesRegex(KeyError, "NEO4J_URI"):
            open_store(env={})

    def test_provider_name_from_environment(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown graph database provider 'nope'"):
            open_store(env={"GRAPH_DB_PROVIDER": "nope"})


if __name__ == "__main__":
    unittest.main()
