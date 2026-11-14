"""Catalog domain tools — catalog.search, inventory.check, pricing.get_quote"""

from __future__ import annotations

from datetime import date
import re
import unicodedata
from typing import Any

from telesale_agent.adapters.db.client import db_client
from mcp_servers.tools.pricing import PricingCalculator

REFERENCE_DATE = date(2026, 10, 15)


def _search_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    ).replace("đ", "d")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())

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
    result = db_client.search_products(
        query=query,
        category=category,
        sku=sku,
        max_price_vnd=max_price_vnd,
        min_room_area_m2=min_room_area_m2,
    )
    if result.get("items") or not query or sku:
        return _filter_requested_variants(result, query)

    # Multi-item utterances do not match one product name as a whole. Resolve
    # every catalog product literally mentioned in the customer query inside
    # this same tool execution, so the agent does not need repeated searches.
    normalized_query = _search_text(query)
    catalog = db_client.search_products(max_price_vnd=max_price_vnd, min_room_area_m2=min_room_area_m2)
    mentioned_items = [
        item
        for item in catalog.get("items", [])
        if isinstance(item, dict)
        and item.get("name")
        and _search_text(str(item["name"])) in normalized_query
    ]
    if mentioned_items:
        return _filter_requested_variants({"items": mentioned_items}, query)

    # LLM queries often include variant words ("Urban Classic 39 đen") and a
    # human category ("Giày sneaker") that do not literally match DB columns.
    # Retry inside the same tool execution so this does not cost another model
    # round-trip or another tool call.
    stopwords = {
        "giày", "giay", "sneaker", "size", "màu", "mau",
        "đen", "den", "trắng", "trang", "xám", "xam",
    }
    tokens = [
        token
        for token in re.findall(r"[\w-]+", query, flags=re.UNICODE)
        if token.casefold() not in stopwords and not token.isdigit()
    ]
    compact_query = " ".join(tokens).strip()
    if compact_query and compact_query.casefold() != query.casefold():
        result = db_client.search_products(
            query=compact_query,
            max_price_vnd=max_price_vnd,
            min_room_area_m2=min_room_area_m2,
        )
    return _filter_requested_variants(result, query)


def _filter_requested_variants(
    result: dict[str, Any], query: str | None
) -> dict[str, Any]:
    """Keep only requested size/color variants to minimize tool payload."""
    if not query or not result.get("items"):
        return result

    normalized = query.casefold()
    size_match = re.search(r"\b(\d{2}|s|m|l|xl)\b", normalized)
    requested_size = size_match.group(1) if size_match else None
    color_aliases = {
        "đen": "den",
        "den": "den",
        "trắng": "trang",
        "trang": "trang",
        "xám": "xam",
        "xam": "xam",
        "navy": "navy",
        "be": "be",
    }
    requested_color = next(
        (value for key, value in color_aliases.items() if key in normalized),
        None,
    )
    if not requested_size and not requested_color:
        return result

    for item in result["items"]:
        variants = item.get("variants") or []
        item["variants"] = [
            variant
            for variant in variants
            if (
                not requested_size
                or str(variant.get("size", "")).casefold() == requested_size
            )
            and (
                not requested_color
                or str(variant.get("color", "")).casefold() == requested_color
            )
        ]
    return result


def inventory_check(sku: str, on: str | None = None) -> dict[str, Any]:
    """Check inventory for a SKU on a given date.

    BTC tool name: inventory.check
    Uses SQLAlchemy to query PostgreSQL inventory events.
    """
    call_date = _today(on)
    return db_client.check_stock(sku, call_date)


def pricing_get_quote(
    sku: str,
    on: str | None = None,
    qty: int = 1,
    customer_phone: str | None = None,
    customer_id: str | None = None,
    address: str | None = None,
    basket_skus: list[str] | None = None,
) -> dict[str, Any]:
    """Quote one unit; use pricing.quote_order for a multi-unit order."""
    return PricingCalculator(db_client, _today(on), customer_phone, customer_id, address).quote(
        sku, qty, basket_skus,
    )


def pricing_quote_order(
    lines: list[dict[str, Any]],
    on: str | None = None,
    customer_phone: str | None = None,
    address: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """Quote every physical unit in one order, including repeated SKUs."""
    return PricingCalculator(db_client, _today(on), customer_phone, customer_id, address).quote_order(lines)

TOOLS = {
    "catalog.search": catalog_search,
    "inventory.check": inventory_check,
    "pricing.get_quote": pricing_get_quote,
    "pricing.quote_order": pricing_quote_order,
}
