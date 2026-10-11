from telesale_agent.core.interfaces import IdentityResolver
from telesale_agent.core.models import CustomerIdentity, TurnContext
from telesale_agent.adapters.db.client import db_client

class HintIdentityResolver(IdentityResolver):
    """Implementation that reads a phone hint and retrieves/creates customer from DB."""

    async def resolve_identity(self, context: TurnContext) -> CustomerIdentity:
        # In a real system, ASR or caller ID provides the phone number
        phone = context.input.customer_hint or "0999999999"
        
        # Check if customer exists in DB
        result = db_client.get_customer(phone=phone)
        
        if result.get("found"):
            # Old user -> return existing CXXX ID
            customer_id = result.get("customer_id")
        else:
            # New user -> create in DB to get a new CXXX ID
            customer_id = db_client.create_customer(phone=phone)
            
        return CustomerIdentity(
            customer_id=customer_id,
            phone=phone,
            confidence=1.0,
            profile={
                "name": result.get("name"),
                "honorific": result.get("honorific"),
            } if result.get("found") and not result.get("ambiguous") else {},
        )
