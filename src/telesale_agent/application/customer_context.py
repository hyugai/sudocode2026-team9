from __future__ import annotations

from telesale_agent.core.interfaces import CRMRetriever, CustomerMemoryRepository
from telesale_agent.core.models import TurnContext


class CustomerContextService:
    """Compose verified CRM data and file-backed memory for one customer."""

    def __init__(
        self,
        crm: CRMRetriever,
        memory: CustomerMemoryRepository,
    ) -> None:
        self.crm = crm
        self.memory = memory

    async def hydrate(self, context: TurnContext) -> None:
        if context.identity is None or not context.identity.customer_id:
            context.state.customer_profile = {}
            context.state.customer_memory = None
            context.state.past_history = {"past_orders": [], "sessions": []}
            return

        customer_id = context.identity.customer_id
        profile = await self.crm.retrieve_profile(context)
        business_history = await self.crm.precompute_brief(context)
        memory = self.memory.load(customer_id)

        # Preserve the source boundary in state. past_history is a compatibility
        # view consumed by existing planners; episodes still originate in memory.
        context.state.customer_profile = profile
        context.state.customer_memory = memory
        context.state.past_history = {
            **business_history,
            "sessions": memory.get("episodes", []),
        }

    def refresh_memory(self, context: TurnContext) -> None:
        """Reload the latest canonical memory without querying CRM again."""
        if context.identity is None or not context.identity.customer_id:
            context.state.customer_memory = None
            return

        memory = self.memory.load(context.identity.customer_id)
        context.state.customer_memory = memory
        business_history = context.state.past_history or {}
        context.state.past_history = {
            **business_history,
            "sessions": memory.get("episodes", []),
        }
