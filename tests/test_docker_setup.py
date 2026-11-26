"""Regression checks for Docker startup against fresh and reused data stores."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, inspect, text

from scripts import setup_docker_data as setup
from scripts.migrate_memory import migrate_memory


class DockerCatalogSetupTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)

    def create_catalog(self, *, missing=None, empty=None, engine=None):
        # The readiness guard inspects names and row presence, independently of
        # PostgreSQL-specific catalog column types.
        with (engine or self.engine).begin() as connection:
            for name in setup.Base.metadata.tables:
                if name != missing:
                    connection.execute(text(f'CREATE TABLE "{name}" (id INTEGER)'))
            for name in ("products", "customers"):
                if name not in (missing, empty):
                    connection.execute(text(f'INSERT INTO "{name}" VALUES (42)'))

    def test_fresh_database_requires_seed_without_creating_tables(self):
        self.assertTrue(setup.catalog_needs_seed(self.engine))
        self.assertEqual(inspect(self.engine).get_table_names(), [])

    def test_complete_catalog_is_reused_without_changing_rows(self):
        self.create_catalog()
        self.assertFalse(setup.catalog_needs_seed(self.engine))
        self.assertFalse(setup.catalog_needs_seed(self.engine))
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT id FROM products")).all(), [(42,)])

    def test_partial_schema_stops_without_repairing_or_resetting(self):
        self.create_catalog(missing="orders")
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            setup.catalog_needs_seed(self.engine)
        self.assertNotIn("orders", inspect(self.engine).get_table_names())
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT id FROM customers")).all(), [(42,)])

    def test_empty_catalog_or_crm_stops(self):
        for empty in ("products", "customers"):
            with self.subTest(empty=empty):
                engine = create_engine("sqlite://")
                try:
                    self.create_catalog(empty=empty, engine=engine)
                    with self.assertRaisesRegex(RuntimeError, "incomplete"):
                        setup.catalog_needs_seed(engine)
                finally:
                    engine.dispose()

    def test_failed_migration_prevents_remaining_startup_steps(self):
        engine = Mock()
        with patch.dict(setup.os.environ, {"DATABASE_URL": "unused"}), \
                patch.object(setup, "create_engine", return_value=engine), \
                patch.object(setup, "catalog_needs_seed", return_value=False), \
                patch.object(setup, "run_script", side_effect=subprocess.CalledProcessError(1, "migration")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                setup.main()
        run.assert_called_once_with("migrate_catalog.py", "--orders-only")
        engine.dispose.assert_called_once()


class MemoryMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / "memory"
        self.seed = self.directory / "crm_seed.json"
        self.customer = {
            "customer_id": "C001", "name": "Seed customer", "phone": "0000000000",
            "sessions": [
                {"session_id": "S1", "date": "2026-01-02", "channel": "phone",
                 "summary": "First seeded session", "outcome": "callback"},
                {"session_id": "S2", "date": "2026-01-02", "channel": "chat",
                 "summary": "Second seeded session", "outcome": "ordered"},
            ],
            "orders": [{"order_id": "O1", "date": "2026-01-03", "sku": "SEED-SKU", "status": "done"}],
        }
        self.write_seed([self.customer])

    def write_seed(self, customers):
        self.seed.write_text(json.dumps({"customers": customers}), encoding="utf-8")

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_creates_memory_only_from_seed_and_groups_sessions_by_date(self):
        self.assertEqual(migrate_memory(self.seed, self.root), (1, 0))
        self.assertEqual(set(self.snapshot()), {
            "C001/user.md", "C001/behaviors.md", "C001/episodes/episode-2026-01-02.md",
            "C001/atomic_facts/fact-2026-01-03.md",
        })
        profile = (self.root / "C001/user.md").read_text(encoding="utf-8")
        self.assertIn("Seed customer", profile)
        episode = (self.root / "C001/episodes/episode-2026-01-02.md").read_text(encoding="utf-8")
        self.assertEqual(episode.count("### Session via"), 2)
        self.assertIn("First seeded session", episode)
        self.assertIn("Second seeded session", episode)

    def test_repeat_preserves_live_memory_and_does_not_duplicate_seed(self):
        migrate_memory(self.seed, self.root)
        (self.root / "C001/user.md").write_text("Updated during a live chat", encoding="utf-8")
        (self.root / "C001/facts.md").write_text("Live fact", encoding="utf-8")
        before = self.snapshot()
        self.assertEqual(migrate_memory(self.seed, self.root), (0, 1))
        self.assertEqual(self.snapshot(), before)

    def test_only_missing_customers_are_added(self):
        migrate_memory(self.seed, self.root)
        before = self.snapshot()
        self.write_seed([self.customer, {"customer_id": "C002", "name": "New seed customer"}])
        self.assertEqual(migrate_memory(self.seed, self.root), (1, 1))
        for path, content in before.items():
            self.assertEqual((self.root / path).read_bytes(), content)
        self.assertTrue((self.root / "C002/user.md").is_file())

    def test_invalid_seed_is_rejected_before_any_destination_is_created(self):
        invalid = (
            [{"customer_id": "../escape"}],
            [self.customer, self.customer],
            [{"customer_id": "C001", "sessions": [{"date": "../../escape"}]}],
            [],
        )
        for customers in invalid:
            with self.subTest(customers=customers):
                self.write_seed(customers)
                with self.assertRaises(ValueError):
                    migrate_memory(self.seed, self.root)
                self.assertFalse(self.root.exists())

    def test_failed_write_leaves_no_partial_customer_and_can_be_retried(self):
        with patch.object(Path, "write_text", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                migrate_memory(self.seed, self.root)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(migrate_memory(self.seed, self.root), (1, 0))


if __name__ == "__main__":
    unittest.main()
