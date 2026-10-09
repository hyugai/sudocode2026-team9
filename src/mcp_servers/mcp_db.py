import os
from mcp.server.fastmcp import FastMCP
from typing import Any

# Import existing tool functions
from telesale_agent.tools.crm import crm_retrieve_profile
from telesale_agent.tools.catalog import catalog_search, inventory_check, pricing_get_quote
from telesale_agent.tools.order import order_create, order_status

# Initialize FastMCP Server
mcp = FastMCP("DB-Server")

@mcp.tool()
def retrieve_customer_profile(phone: str = None, zalo_id: str = None, fb_id: str = None) -> dict[str, Any]:
    """Retrieve customer profile and history by phone or social ID."""
    return crm_retrieve_profile(phone=phone, zalo_id=zalo_id, fb_id=fb_id)

@mcp.tool()
def search_catalog(query: str = None, category: str = None, sku: str = None, max_price_vnd: int = None) -> dict[str, Any]:
    """Search for products in the catalog."""
    return catalog_search(query=query, category=category, sku=sku, max_price_vnd=max_price_vnd)

@mcp.tool()
def check_inventory(sku: str, on: str = None) -> dict[str, Any]:
    """Check inventory for a specific SKU."""
    return inventory_check(sku=sku, on=on)

@mcp.tool()
def get_pricing_quote(cart_skus: list[str], cart_categories: list[str], region: str) -> dict[str, Any]:
    """Get active promotions and pricing rules."""
    return pricing_get_quote(cart_skus=cart_skus, cart_categories=cart_categories, region=region)

@mcp.tool()
def create_new_order(customer_id: str, sku: str, price_vnd: int, delivery_address: str, payment_method: str) -> dict[str, Any]:
    """Create a new order in the system."""
    return order_create(customer_id=customer_id, sku=sku, price_vnd=price_vnd, delivery_address=delivery_address, payment_method=payment_method)

@mcp.tool()
def check_order_status(order_id: str) -> dict[str, Any]:
    """Check the status of an existing order."""
    return order_status(order_id=order_id)

if __name__ == "__main__":
    mcp.run()
