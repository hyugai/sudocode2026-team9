import logging
from typing import Any, Dict

from telesale_agent.core.models import TurnContext
from telesale_agent.core.interfaces import CRMRetriever
from telesale_agent.adapters.db.client import db_client

logger = logging.getLogger(__name__)


class PostgresCRMRetriever(CRMRetriever):
    """
    CRM retriever backed by PostgreSQL via SQLAlchemy.

    CRM owns verified customer and transactional data. Learned preferences and
    conversation episodes are loaded by CustomerMemoryRepository instead.
    """

    async def retrieve_profile(self, ctx: TurnContext) -> Dict[str, Any]:
        """Fetch customer profile based on phone number from identity context."""
        if not ctx.identity or not ctx.identity.customer_id:
            logger.debug("No customer_id in context. Returning empty profile.")
            return {}

        customer_id = str(ctx.identity.customer_id).strip()
        result = db_client.get_customer_by_id(customer_id)

        if not result.get("found"):
            logger.info("No customer found in PostgreSQL for customer_id=%s", customer_id)
            return {
                "customer_id": customer_id,
                "phone": ctx.identity.phone,
                "is_new_customer": True,
            }

        if result.get("ambiguous"):
            logger.warning("Ambiguous CRM identity for customer_id=%s", customer_id)
            return {
                "customer_id": customer_id,
                "phone": ctx.identity.phone,
                "is_ambiguous": True,
                "candidates": result.get("candidates", [])
            }

        # Do not flatten attributes or return session memory through the CRM port.
        return {
            "found": True,
            "customer_id": result.get("customer_id"),
            "name": result.get("name"),
            "honorific": result.get("honorific"),
            "phone": result.get("phone"),
            "region": result.get("region"),
        }

    async def precompute_brief(self, ctx: TurnContext) -> Dict[str, Any]:
        """Fetch verified order history for the customer."""
        if not ctx.identity or not ctx.identity.customer_id:
            return {"past_orders": []}

        customer_id = str(ctx.identity.customer_id).strip()
        result = db_client.get_customer_by_id(customer_id)

        if not result.get("found") or result.get("ambiguous"):
            return {"past_orders": []}

        return {
            "past_orders": result.get("orders", []),
        }


# Compatibility alias. New code should use PostgresCRMRetriever.
SupabaseCRMRetriever = PostgresCRMRetriever
