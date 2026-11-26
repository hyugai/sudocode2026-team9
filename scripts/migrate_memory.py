"""Seed missing customer memory from organizer CRM JSON; never import local memory."""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = PROJECT_ROOT / "dataset" / "organizer" / "catalog" / "crm_seed.json"
DEFAULT_MEMORY_ROOT = PROJECT_ROOT / "data" / "memory-root" / "users"


def customer_files(customer: dict) -> dict[str, str]:
    """Render only facts supplied by a single CRM seed record."""
    fields = (
        ("customer_id", "Customer ID"), ("name", "Name"),
        ("honorific", "Honorific"), ("phone", "Phone"), ("region", "Region"),
        ("zalo_id", "Zalo ID"), ("fb_id", "Facebook ID"),
        ("shared_phone_with", "Shared phone with"),
    )
    profile = ["# User Profile", ""]
    profile.extend(
        f"- {label}: {customer[key]}"
        for key, label in fields if customer.get(key) is not None
    )
    files = {
        "user.md": "\n".join(profile) + "\n",
        "behaviors.md": "# Behavioral Patterns\n\n",
    }
    for session in customer.get("sessions", []):
        occurred_on = date.fromisoformat(session["date"]).isoformat()
        path = f"episodes/episode-{occurred_on}.md"
        files[path] = files.get(path, "") + (
            f"### Session via {session.get('channel', '')} at {occurred_on}\n"
            f"Source: crm_seed.json / {session.get('session_id', '')}\n"
            f"Outcome: {session.get('outcome', '')}\n"
            f"Summary: {session.get('summary', '')}\n\n"
        )
    for order in customer.get("orders", []):
        occurred_on = date.fromisoformat(order["date"]).isoformat()
        path = f"atomic_facts/fact-{occurred_on}.md"
        files[path] = files.get(path, "") + (
            f"- Ordered SKU: {order.get('sku', '')} (Status: {order.get('status', '')})\n"
        )
    return files


def migrate_memory(seed_file: Path, memory_root: Path) -> tuple[int, int]:
    """Create each customer's tree atomically; preserve existing live memory."""
    data = json.loads(seed_file.read_text(encoding="utf-8"))
    customers = data.get("customers")
    if not isinstance(customers, list) or not customers:
        raise ValueError("CRM seed must contain a non-empty customers list")

    # Validate/render the entire source before creating any destination files.
    prepared = {}
    for customer in customers:
        customer_id = customer.get("customer_id")
        if not isinstance(customer_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", customer_id):
            raise ValueError("CRM seed contains an invalid customer_id")
        if customer_id in prepared:
            raise ValueError("CRM seed contains a duplicate customer_id")
        prepared[customer_id] = customer_files(customer)

    memory_root.mkdir(parents=True, exist_ok=True)
    created = skipped = 0
    for customer_id, files in prepared.items():
        destination = memory_root / customer_id
        if destination.exists():
            skipped += 1
            continue
        # A failed write never leaves a half-seeded customer directory behind.
        with tempfile.TemporaryDirectory(prefix=".crm-seed-", dir=memory_root) as temporary:
            staged = Path(temporary) / customer_id
            staged.mkdir()
            for name in ("episodes", "atomic_facts", "foresights"):
                (staged / name).mkdir()
            for name, content in files.items():
                (staged / name).write_text(content, encoding="utf-8")
            staged.rename(destination)
        created += 1
    return created, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-file", type=Path, default=SEED_FILE)
    parser.add_argument("--memory-root", type=Path,
                        default=Path(os.environ.get("CUSTOMER_MEMORY_ROOT") or DEFAULT_MEMORY_ROOT))
    args = parser.parse_args()
    created, skipped = migrate_memory(args.seed_file, args.memory_root)
    print(f"CRM memory ready: {created} customers created; {skipped} existing customers preserved.")


if __name__ == "__main__":
    main()
