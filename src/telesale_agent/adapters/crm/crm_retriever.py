import logging
from typing import Any, Dict

from telesale_agent.core.models import TurnContext
from telesale_agent.core.interfaces import CRMRetriever
from telesale_agent.adapters.db.client import db_client

logger = logging.getLogger(__name__)


class SupabaseCRMRetriever(CRMRetriever):
    """
    CRM Retriever that fetches customer profile from Supabase via SQLAlchemy.
    Replaces FileCRMRetriever — no longer reads from local JSON seed file.
    """

    async def retrieve_profile(self, ctx: TurnContext) -> Dict[str, Any]:
        """Fetch customer profile based on phone number from identity context."""
        if not ctx.identity or not ctx.identity.customer_id:
            logger.debug("No customer_id in context. Returning empty profile.")
            return {}

        phone = str(ctx.identity.customer_id).strip()
        result = db_client.get_customer(phone=phone)

        if not result.get("found"):
            logger.info(f"No customer found in Supabase for phone={phone}. Treating as new customer.")
            return {"phone": phone, "is_new_customer": True}

        if result.get("ambiguous"):
            logger.warning(f"Ambiguous phone={phone}: multiple customers share this number.")
            return {
                "phone": phone,
                "is_ambiguous": True,
                "candidates": result.get("candidates", [])
            }

        # Combined attributes to a profile dictionary
        profile = dict(result)
        if "attributes" in result:
            profile.update(result["attributes"])
            
        return profile

    async def precompute_brief(self, ctx: TurnContext) -> Dict[str, Any]:
        """Fetch past orders and session history for the customer."""
        if not ctx.identity or not ctx.identity.customer_id:
            return {"past_orders": [], "sessions": []}

        phone = str(ctx.identity.customer_id).strip()
        result = db_client.get_customer(phone=phone)

        if not result.get("found") or result.get("ambiguous"):
            return {"past_orders": [], "sessions": []}

        return {
            "past_orders": result.get("orders", []),
            "sessions": result.get("sessions", [])
        }
