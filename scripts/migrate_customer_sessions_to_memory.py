"""Export legacy customer_sessions to file memory, then optionally drop the table."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from dotenv import load_dotenv
from sqlalchemy import inspect, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
load_dotenv(PROJECT_ROOT / ".env")

from telesale_agent.adapters.db.client import db_client  # noqa: E402
from telesale_agent.adapters.memory import FileCustomerMemoryRepository  # noqa: E402


def migrate(*, drop_table: bool) -> tuple[int, int]:
    engine = db_client.engine
    if not inspect(engine).has_table("customer_sessions"):
        print("customer_sessions does not exist; nothing to migrate.")
        return 0, 0

    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT session_id, customer_id, session_date, channel, summary, outcome
            FROM customer_sessions
            ORDER BY customer_id, session_date, session_id
        """)).mappings().all()

    repository = FileCustomerMemoryRepository()
    exported = 0
    for row in rows:
        occurred_on = str(row["session_date"]) if row["session_date"] else None
        narrative = (
            f"Channel: {row['channel'] or 'unknown'}\n"
            f"Outcome: {row['outcome'] or 'unknown'}\n"
            f"Summary: {row['summary'] or ''}"
        )
        repository.record_episode(
            str(row["customer_id"]),
            narrative,
            occurred_on=occurred_on,
            source_id=str(row["session_id"]),
        )
        exported += 1

    if exported != len(rows):
        raise RuntimeError(f"Export verification failed: {exported}/{len(rows)}")

    print(f"Exported {exported} customer_sessions rows to .md episode files.")
    if drop_table:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE customer_sessions"))
        print("Dropped PostgreSQL table customer_sessions.")
    else:
        print("Table retained. Re-run with --drop-table after reviewing exported files.")

    return len(rows), exported


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--drop-table",
        action="store_true",
        help="Drop customer_sessions only after every row has been exported.",
    )
    args = parser.parse_args()
    migrate(drop_table=args.drop_table)


if __name__ == "__main__":
    main()
