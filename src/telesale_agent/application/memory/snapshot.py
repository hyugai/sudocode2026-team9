"""A single Markdown document containing one customer's durable memory."""

from __future__ import annotations

import json
import re
from typing import Any


_DOCUMENT = re.compile(
    r"\A# Customer Memory\n\n```json\n(?P<payload>.*?)\n```\n?\Z",
    re.DOTALL,
)
_COLLECTIONS = ("atomic_facts", "episodes", "foresights")


def empty_snapshot(customer_id: str) -> dict[str, Any]:
    return {
        "customer_id": customer_id,
        "profile": "",
        "behaviors": "",
        "facts": {},
        **{name: [] for name in _COLLECTIONS},
    }


def render_snapshot(snapshot: dict[str, Any]) -> str:
    """Keep the storage object a .md file while retaining exact typed facts."""
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
    return f"# Customer Memory\n\n```json\n{payload}\n```\n"


def parse_snapshot(document: str, customer_id: str) -> dict[str, Any]:
    match = _DOCUMENT.fullmatch(document)
    if not match:
        raise ValueError("Invalid customer memory Markdown snapshot")
    parsed = json.loads(match.group("payload"))
    if not isinstance(parsed, dict) or parsed.get("customer_id") != customer_id:
        raise ValueError("Customer memory snapshot has a mismatched customer_id")
    result = empty_snapshot(customer_id)
    result.update(parsed)
    if not isinstance(result["facts"], dict) or any(
        not isinstance(result[name], list) for name in _COLLECTIONS
    ):
        raise ValueError("Customer memory snapshot has invalid collections")
    return result
