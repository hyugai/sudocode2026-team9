from telesale_agent.core.interfaces import Persister
from telesale_agent.core.models import TurnContext

class InMemoryPersister(Persister):
    """Local demo that simulates saving memory without external storage."""

    async def persist(self, context: TurnContext) -> list[dict]:
        if context.state is None:
            return []

        for step in context.steps:
            if step.action_result.status.value == "executed":
                # For demo purposes, we log that a tool succeeded.
                pass
        return []
