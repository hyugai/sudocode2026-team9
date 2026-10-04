"""CRM domain tools — crm.get_customer"""

from __future__ import annotations
from typing import Any

from telesale_agent.adapters.db.client import db_client


def crm_get_customer(
    phone: str | None = None,
    zalo_id: str | None = None,
    fb_id: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Look up a customer by phone or channel identity.

    BTC tool name: crm.get_customer
    Uses SQLAlchemy to query Supabase database.
    """
    return db_client.get_customer(phone=phone, zalo_id=zalo_id, fb_id=fb_id)


TOOLS = {
    "crm.get_customer": crm_get_customer,
}
