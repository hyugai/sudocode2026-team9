from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Any

from telesale_agent.core.interfaces import CustomerMemoryRepository


def _empty_memory(customer_id: str) -> dict[str, Any]:
    return {
        "customer_id": customer_id,
        "profile": "",
        "behaviors": "",
        "facts": {},
        "atomic_facts": [],
        "episodes": [],
        "foresights": [],
    }


class InMemoryCustomerMemoryRepository:
    """Isolated customer memory for evaluations and tests.

    An optional read-only seed repository can provide initial memory. Every
    write remains in this process and ``reset()`` restores the clean seed.
    """

    def __init__(
        self,
        seed: CustomerMemoryRepository | None = None,
        *,
        daily_files: bool = False,
        default_day: str | None = None,
    ):
        self.seed = seed
        self.daily_files = daily_files
        self.default_day = default_day
        self._customers: dict[str, dict[str, Any]] = {}
        self._latest: dict[str, dict[str, Any]] = {}
        self._sequence = 0

    def reset(self) -> None:
        self._customers.clear()
        self._latest.clear()
        self._sequence = 0

    def seed_snapshot(self, customer_id: str, snapshot: dict[str, Any]) -> None:
        """Install an already-loaded snapshot without reading its source again."""
        self._customers[customer_id] = deepcopy(snapshot)
        self._customers[customer_id].setdefault("facts", {})
        for collection in ("atomic_facts", "episodes", "foresights"):
            for item in self._customers[customer_id].get(collection, []):
                match = re.search(r"-(\d+)\.md$", str(item.get("source", "")))
                if match:
                    self._sequence = max(self._sequence, int(match.group(1)))

    def _ensure(self, customer_id: str) -> dict[str, Any]:
        if customer_id not in self._customers:
            initial = self.seed.load(customer_id) if self.seed else _empty_memory(customer_id)
            initial.setdefault("facts", {})
            self._customers[customer_id] = deepcopy(initial)
        return self._customers[customer_id]

    def load(self, customer_id: str) -> dict[str, Any]:
        return deepcopy(self._ensure(customer_id))

    def latest_fact(self, customer_id: str, key: str) -> Any:
        return self._ensure(customer_id).get("facts", {}).get(key)

    def remember_latest_fact(self, customer_id: str, key: str, value: Any) -> None:
        self._latest.setdefault(customer_id, {})[key] = deepcopy(value)

    def upsert_fact(
        self, customer_id: str, key: str, value: Any
    ) -> dict[str, Any]:
        memory = self._ensure(customer_id)
        facts = memory.setdefault("facts", {})
        action = "updated" if key in facts else "created"
        facts[key] = deepcopy(value)
        self.remember_latest_fact(customer_id, key, value)
        return {
            "status": "success",
            "file": "memory://facts.md",
            "action": action,
        }

    def update_profile(self, customer_id: str, fact: str) -> dict[str, Any]:
        memory = self._ensure(customer_id)
        memory["profile"] = f"{memory.get('profile', '').rstrip()}\n- {fact}".strip()
        return {"status": "success", "file": "memory://user.md", "action": "updated"}

    def update_behaviors(self, customer_id: str, pattern: str) -> dict[str, Any]:
        memory = self._ensure(customer_id)
        memory["behaviors"] = (
            f"{memory.get('behaviors', '').rstrip()}\n- {pattern}".strip()
        )
        return {
            "status": "success",
            "file": "memory://behaviors.md",
            "action": "updated",
        }

    def _append(
        self,
        customer_id: str,
        collection: str,
        prefix: str,
        content: str,
        *,
        occurred_on: str | None = None,
        source_id: str | None = None,
    ):
        if self.daily_files:
            day = occurred_on or self.default_day or datetime.now().strftime("%Y-%m-%d")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                raise ValueError("Invalid memory date")
            source = f"{prefix}-{day}.md"
            items = self._ensure(customer_id)[collection]
            existing = next(
                (item for item in items if item.get("source") == source), None
            )
            if source_id and existing and f"<!-- source_id:{source_id} -->" in existing["content"]:
                return {
                    "status": "success",
                    "file": f"memory://{collection}/{source}",
                    "action": "skipped",
                }
            if (
                collection == "foresights"
                and existing
                and content in existing["content"].splitlines()
            ):
                return {
                    "status": "success",
                    "file": f"memory://{collection}/{source}",
                    "action": "skipped",
                }
            if source_id:
                content = f"<!-- source_id:{source_id} -->\n{content}"
            if existing:
                existing["content"] = existing["content"].rstrip() + "\n" + content + "\n"
            else:
                items.append({"source": source, "content": content + "\n"})
            return {"status": "success", "file": f"memory://{collection}/{source}"}
        self._sequence += 1
        source = f"{prefix}-{self._sequence:04d}.md"
        self._ensure(customer_id)[collection].append(
            {"source": source, "content": content}
        )
        return {"status": "success", "file": f"memory://{collection}/{source}"}

    def record_atomic_fact(self, customer_id: str, fact: str) -> dict[str, Any]:
        return self._append(customer_id, "atomic_facts", "fact", f"- {fact}")

    def record_foresight(self, customer_id: str, foresight: str) -> dict[str, Any]:
        return self._append(customer_id, "foresights", "foresight", f"- {foresight}")

    def record_episode(
        self,
        customer_id: str,
        summary: str,
        *,
        occurred_on: str | None = None,
        source_id: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        return self._append(
            customer_id,
            "episodes",
            "episode",
            summary,
            occurred_on=occurred_on,
            source_id=source_id,
        )

