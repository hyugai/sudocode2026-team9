"""Prepare the local Compose data volumes before starting the API."""

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.migrate_catalog import Base  # noqa: E402


def catalog_needs_seed(engine: Engine) -> bool:
    """Reuse a complete catalog; stop on a partial seed without resetting data."""
    tables = set(Base.metadata.tables)
    with engine.connect() as connection:
        present = tables.intersection(inspect(connection).get_table_names())
        if not present:
            return True
        if present == tables and connection.execute(text(
            "SELECT EXISTS (SELECT 1 FROM products) AND EXISTS (SELECT 1 FROM customers)"
        )).scalar_one():
            return False
    raise RuntimeError(
        "Catalog/CRM is incomplete. Inspect the database before retrying; no data was reset."
    )


def run_script(name: str, *arguments: str) -> None:
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / name), *arguments],
        cwd=PROJECT_ROOT,
        check=True,
    )


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], connect_args={"connect_timeout": 5})
    try:
        needs_seed = catalog_needs_seed(engine)
    finally:
        engine.dispose()

    run_script("migrate_catalog.py", *(() if needs_seed else ("--orders-only",)))
    for script in ("migrate_app_data.py", "migrate_voice.py", "migrate_learning.py"):
        run_script(script)
    run_script("migrate_memory.py")
    run_script("ingest_policy.py", "--if-empty")

    if os.environ.get("DOWNLOAD_ASR_MODEL", "false").strip().lower() == "true":
        run_script("download_asr_model.py")
    print("Docker data ready.", flush=True)


if __name__ == "__main__":
    main()
