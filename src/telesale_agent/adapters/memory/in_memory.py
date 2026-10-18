from __future__ import annotations

from copy import deepcopy
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

    def __init__(self, seed: CustomerMemoryRepository | None = None):
        self.seed = seed
        self._customers: dict[str, dict[str, Any]] = {}
        self._latest: dict[str, dict[str, Any]] = {}
        self._sequence = 0

    def reset(self) -> None:
        self._customers.clear()
        self._latest.clear()
        self._sequence = 0

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

    def _append(self, customer_id: str, collection: str, prefix: str, content: str):
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

    def record_episode(self, customer_id: str, summary: str, **_: Any) -> dict[str, Any]:
        return self._append(customer_id, "episodes", "episode", summary)

