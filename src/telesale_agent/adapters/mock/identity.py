from telesale_agent.core.interfaces import IdentityResolver
from telesale_agent.core.models import CustomerIdentity, TurnContext

class HintIdentityResolver(IdentityResolver):
    """Local demo implementation that reads a hint from the request."""

    async def resolve_identity(self, context: TurnContext) -> CustomerIdentity:
        hint = context.input.customer_hint or "CUST_000"
        return CustomerIdentity(
            customer_id=hint,
            confidence=0.9,
            profile={},
        )
