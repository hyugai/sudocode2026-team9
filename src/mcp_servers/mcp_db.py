import os
from mcp.server.fastmcp import FastMCP
from typing import Any
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import existing tool functions
from mcp_servers.tools.crm import crm_get_customer
from mcp_servers.tools.catalog import catalog_search, inventory_check, pricing_get_quote
from mcp_servers.tools.order import order_create, order_status

# Initialize FastMCP Server
mcp = FastMCP("DB-Server")

@mcp.tool()
def retrieve_customer_profile(
    phone: str | None = None,
    zalo_id: str | None = None,
    fb_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve customer profile and history by phone or social ID."""
    return crm_get_customer(phone=phone, zalo_id=zalo_id, fb_id=fb_id)

@mcp.tool()
def search_catalog(
    query: str | None = None,
    category: str | None = None,
    sku: str | None = None,
    max_price_vnd: int | None = None,
) -> dict[str, Any]:
    """Search for products in the catalog."""
    return catalog_search(query=query, category=category, sku=sku, max_price_vnd=max_price_vnd)

@mcp.tool()
def check_inventory(sku: str, on: str | None = None) -> dict[str, Any]:
    """Check inventory for a specific SKU."""
    return inventory_check(sku=sku, on=on)

@mcp.tool()
def get_pricing_quote(
    sku: str,
    qty: int = 1,
    basket_skus: list[str] | None = None,
    customer_phone: str | None = None,
    address: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Get active promotions and pricing rules."""
    return pricing_get_quote(
        sku=sku,
        qty=qty,
        basket_skus=basket_skus,
        customer_phone=customer_phone,
        address=address,
        on=on,
    )

@mcp.tool()
def create_new_order(
    customer_phone: str,
    sku: str,
    price_vnd: int,
    qty: int,
    payment_method: str = "COD",
    address: str | None = None,
    promo_code: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Create a new order in the system."""
    return order_create(
        customer_phone=customer_phone,
        sku=sku,
        qty=qty,
        price_vnd=price_vnd,
        promo_code=promo_code,
        payment=payment_method,
        address=address,
        on=on,
    )

@mcp.tool()
def check_order_status(
    order_id: str | None = None,
    customer_phone: str | None = None,
) -> dict[str, Any]:
    """Check the status of an existing order."""
    return order_status(order_id=order_id, customer_phone=customer_phone)

if __name__ == "__main__":
    mcp.run()
