"""Memory repository adapter for the application-owned turn persistence flow."""

from __future__ import annotations

from typing import Any

from telesale_agent.core.interfaces import CustomerMemoryRepository, Persister
from telesale_agent.core.models import TurnContext
from telesale_agent.application.memory.persist import persist_turn_memory
from telesale_agent.application.memory.turn_facts import _tool_memory_candidates


class TurnMemoryPersister(Persister):
    """Persist structured turn facts without making another LLM request."""

    def __init__(self, memory: CustomerMemoryRepository):
        self.memory = memory

    async def persist(self, context: TurnContext) -> list[dict[str, Any]]:
        return persist_turn_memory(self.memory, context)
