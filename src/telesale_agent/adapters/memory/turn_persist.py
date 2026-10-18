"""Memory repository adapter for the application-owned turn persistence flow."""

from __future__ import annotations

from typing import Any

from telesale_agent.core.interfaces import CustomerMemoryRepository, Persister, SnapshotMemoryStore
from telesale_agent.core.models import TurnContext
from telesale_agent.application.memory.persist import persist_turn_memory
from telesale_agent.application.memory.turn_facts import _tool_memory_candidates
from .write_session import TurnMemoryWriteSession


class TurnMemoryPersister(Persister):
    """Persist structured turn facts without making another LLM request."""

    def __init__(self, memory: CustomerMemoryRepository | SnapshotMemoryStore):
        self.memory = memory

    async def persist(self, context: TurnContext) -> list[dict[str, Any]]:
        session = TurnMemoryWriteSession(self.memory, context)
        writes = persist_turn_memory(session.repository, context)
        await session.commit()
        return writes
