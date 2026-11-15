"""Add nullable orders.lines without reseeding or rewriting existing orders."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import inspect, text
from telesale_agent.adapters.db.app_schema import create_app_engine


def migrate_order_lines(engine) -> bool:
    """Return whether the column was missing; safe to run more than once."""
    if engine.dialect.name not in {"postgresql", "sqlite"}:
        raise ValueError("Unsupported database dialect")
    with engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table("orders"):
            raise ValueError("Chưa có bảng orders. Thiết lập schema CRM trước.")
        existing = {column["name"] for column in inspector.get_columns("orders")}
        if engine.dialect.name == "postgresql":
            # IF NOT EXISTS also makes concurrent deployment attempts safe.
            connection.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS lines JSONB"))
        elif "lines" not in existing:
            # SQLite is used only by the isolated migration regression tests.
            connection.execute(text("ALTER TABLE orders ADD COLUMN lines JSON"))
        return "lines" not in existing


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    engine = None
    try:
        engine = create_app_engine()
        if engine.dialect.name != "postgresql":
            raise ValueError("Migration triển khai yêu cầu PostgreSQL.")
        added = migrate_order_lines(engine)
        print("Added orders.lines JSONB." if added else "orders.lines already exists; no rows changed.")
        return 0
    except Exception as exc:
        print(f"Order migration failed ({type(exc).__name__}). Kiểm tra cấu hình/kết nối DB.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
