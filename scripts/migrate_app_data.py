"""Run: python scripts/migrate_app_data.py [--inspect-only]. Never resets CRM."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import inspect, text
from telesale_agent.adapters.db.app_schema import create_app_engine, migrate_app_data


def inspect_database(engine) -> dict:
    """Only table names, row counts and size; no credentials/customer contents."""
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout = '10s'"))
        quote = connection.dialect.identifier_preparer.quote
        tables = [{"table": name, "rows": connection.execute(
            text("SELECT count(*) FROM " + quote(name))).scalar_one()}
            for name in sorted(inspect(connection).get_table_names())]
        size = connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
        return {"database_bytes": size, "tables": tables}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-only", action="store_true", help="Chỉ đọc số lượng dữ liệu, không tạo bảng")
    args = parser.parse_args()
    engine = None
    try:
        engine = create_app_engine()
        if args.inspect_only:
            print(json.dumps(inspect_database(engine), ensure_ascii=False))
        else:
            print("Application tables ready: " + ", ".join(migrate_app_data(engine)))
        return 0
    except Exception as exc:
        # Driver/SQLAlchemy errors may contain URLs or SQL parameters.
        print(f"Database operation failed ({type(exc).__name__}). Kiểm tra cấu hình/kết nối và schema CRM.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
