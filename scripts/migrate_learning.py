"""Create the additive self-learning tables: python scripts/migrate_learning.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from telesale_agent.adapters.db.app_schema import create_app_engine
from telesale_agent.adapters.db.learning import migrate_learning


def main():
    engine = None
    try:
        engine = create_app_engine()
        print("Learning tables ready: " + ", ".join(migrate_learning(engine)))
        return 0
    except Exception as exc:
        print(f"Learning migration failed ({type(exc).__name__}). Kiểm tra cấu hình/schema.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
