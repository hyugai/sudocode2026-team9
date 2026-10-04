"""Catalog domain tools — catalog.search, inventory.check, pricing.get_quote"""

from __future__ import annotations

from datetime import date
from typing import Any

from telesale_agent.adapters.db.client import db_client

REFERENCE_DATE = date(2026, 10, 15)

def _today(on: str | None) -> date:
    return date.fromisoformat(on) if on else REFERENCE_DATE

def catalog_search(
    query: str | None = None,
    category: str | None = None,
    sku: str | None = None,
    max_price_vnd: int | None = None,
    min_room_area_m2: int | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Search the product catalog.

    BTC tool name: catalog.search
    """
    # Khai báo mapping các danh mục con nếu cần hoặc để query thẳng DB
    # Giữ nguyên logic query qua SQLAlchemy
    return db_client.search_products(query=query, category=category, sku=sku, max_price_vnd=max_price_vnd)


def inventory_check(sku: str, on: str | None = None) -> dict[str, Any]:
    """Check inventory for a SKU on a given date.

    BTC tool name: inventory.check
    Uses SQLAlchemy to query Supabase inventory events.
    """
    call_date = _today(on)
    return db_client.check_stock(sku, call_date)


def pricing_get_quote(
    sku: str,
    on: str | None = None,
    qty: int = 1,
    customer_phone: str | None = None,
    address: str | None = None,
    basket_skus: list | None = None,
) -> dict[str, Any]:
    """Calculate final price including applicable promotions.

    BTC tool name: pricing.get_quote
    """
    call_date = _today(on)
    
    # Lấy giá gốc của sản phẩm
    product_res = db_client.search_products(sku=sku)
    if not product_res["items"]:
        return {"error": "product_not_found"}
        
    product = product_res["items"][0]
    list_price = product.get("list_price_vnd", 0)
    category = product.get("category", "")
    
    skus_in_basket = basket_skus or []
    skus_in_basket.append(sku)
    categories_in_basket = [category]
    
    # Lấy danh sách promotions hợp lệ
    # Chú ý: Cần biết region của customer nếu muốn check điều kiện freeship theo miền
    # Ở đây default region truyền vào None, DB Client sẽ bỏ qua các rule có specific region
    active_promos = db_client.get_active_promotions(
        cart_skus=skus_in_basket, 
        cart_categories=categories_in_basket, 
        region=None, 
        current_date=call_date
    )
    
    best_discount = 0
    applied_promos = []
    
    for promo in active_promos:
        disc = promo.get("discount_percent", 0)
        if disc > best_discount:
            best_discount = disc
            applied_promos = [promo["promotion_id"]]

    final_price = int(list_price * (1 - best_discount / 100))
    freeship = (final_price * qty) >= 1_500_000

    return {
        "list_price_vnd": list_price,
        "final_price_vnd": final_price,
        "applied_promos": applied_promos,
        "expired_promos": [], # Lịch sử expired không cần thiết nếu query trực tiếp
        "ineligible_promos": [],
        "not_applied_exclusive": [],
        "freeship": freeship,
    }

TOOLS = {
    "catalog.search": catalog_search,
    "inventory.check": inventory_check,
    "pricing.get_quote": pricing_get_quote,
}
