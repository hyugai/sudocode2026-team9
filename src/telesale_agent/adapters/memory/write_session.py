"""A per-turn memory workspace; remote storage is committed only once."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, cast

from .in_memory import InMemoryCustomerMemoryRepository
from telesale_agent.core.interfaces import CustomerMemoryRepository, SnapshotMemoryStore
from telesale_agent.core.models import TurnContext


class TurnMemoryWriteSession:
    """Use existing fact/episode logic against RAM, then commit one snapshot."""

    def __init__(
        self, store: CustomerMemoryRepository | SnapshotMemoryStore, context: TurnContext
    ):
        self.store = store
        self.context = context
        self.customer_id = (
            context.identity.customer_id
            if context.identity and context.identity.customer_id
            else None
        )
        self.initial: dict[str, Any] | None = None
        self.original_deltas = deepcopy(context.state.memory_deltas)
        self.repository: CustomerMemoryRepository = cast(CustomerMemoryRepository, store)

        if self.customer_id and callable(getattr(store, "save_snapshot", None)):
            # CustomerContextService already fetched this at the start of turn.
            self.initial = deepcopy(
                context.state.customer_memory
                if context.state.customer_memory is not None
                else store.load(self.customer_id)
            )
            call_date = context.input.metadata.get("call_date")
            working = InMemoryCustomerMemoryRepository(
                daily_files=True,
                default_day=call_date if isinstance(call_date, str) else None,
            )
            working.seed_snapshot(self.customer_id, self.initial)
            self.repository = working

    async def commit(self) -> None:
        if self.initial is None or self.customer_id is None:
            return
        snapshot = self.repository.load(self.customer_id)
        if snapshot != self.initial:
            try:
                # Network I/O must not block the async agent event loop.
                await asyncio.to_thread(
                    cast(SnapshotMemoryStore, self.store).save_snapshot,
                    self.customer_id,
                    snapshot,
                    previous_snapshot=self.initial,
                )
            except Exception:
                self.context.state.customer_memory = self.initial
                self.context.state.memory_deltas.update(self.original_deltas)
                raise
        self.context.state.customer_memory = snapshot
