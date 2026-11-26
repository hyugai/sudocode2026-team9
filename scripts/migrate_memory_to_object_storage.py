"""Import local Markdown memory and repair missing per-customer archive objects."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
load_dotenv(PROJECT_ROOT / ".env")

from telesale_agent.adapters.memory import (  # noqa: E402
    FileCustomerMemoryRepository,
    ObjectStorageCustomerMemoryRepository,
)
from telesale_agent.application.memory.snapshot import empty_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, help="Local customer-memory root")
    parser.add_argument("--customer-id", help="Import or repair just one customer, e.g. C031")
    parser.add_argument("--apply", action="store_true", help="Actually upload snapshots")
    parser.add_argument("--overwrite", action="store_true", help="Replace non-empty remote snapshots")
    args = parser.parse_args()
    if args.customer_id and not re.fullmatch(r"[A-Za-z0-9_-]+", args.customer_id):
        parser.error("--customer-id contains unsupported characters")

    source = FileCustomerMemoryRepository(args.source_root)
    if not source.root.is_dir():
        raise SystemExit(f"Source directory not found: {source.root}")
    customer_ids = sorted(
        path.name
        for path in source.root.iterdir()
        if path.is_dir() and re.fullmatch(r"[A-Za-z0-9_-]+", path.name)
    )
    if args.customer_id:
        if args.customer_id not in customer_ids:
            raise SystemExit(f"Local customer directory not found: {args.customer_id}")
        customer_ids = [args.customer_id]
    print(f"Found {len(customer_ids)} local customer directories.")
    if not args.apply:
        print("Dry-run only. Add --apply to upload; remote storage was not contacted.")
        return

    destination = ObjectStorageCustomerMemoryRepository()
    uploaded = repaired = skipped = 0
    for customer_id in customer_ids:
        snapshot = source.load(customer_id)
        remote = destination.load(customer_id)
        if remote != empty_snapshot(customer_id) and not args.overwrite:
            if destination.has_current(customer_id):
                # Never replace newer live facts with older local ones. Only
                # fill missing archive objects, including local old dates.
                repaired += destination.backfill_files(customer_id, snapshot)
                continue
            snapshot = remote  # Upgrade the old remote snapshot first.
        if snapshot == empty_snapshot(customer_id):
            skipped += 1
            continue
        destination.save_snapshot(customer_id, snapshot)
        uploaded += 1
        if remote != empty_snapshot(customer_id) and not args.overwrite:
            repaired += destination.backfill_files(customer_id, source.load(customer_id))
    print(f"Current files created/replaced: {uploaded}; archive objects repaired: {repaired}; skipped: {skipped}.")


if __name__ == "__main__":
    main()
