"""Catalog domain tools — catalog.search, inventory.check, pricing.get_quote"""

from __future__ import annotations

from datetime import date
import re
import unicodedata
from typing import Any

from telesale_agent.adapters.db.client import db_client

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
    )
    if result.get("items") or not query or sku:
        return _filter_requested_variants(result, query)

    # Multi-item utterances do not match one product name as a whole. Resolve
    # every catalog product literally mentioned in the customer query inside
    # this same tool execution, so the agent does not need repeated searches.
    normalized_query = _search_text(query)
    catalog = db_client.search_products()
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
    basket_skus: list | None = None,
) -> dict[str, Any]:
    """Calculate final price including applicable promotions.

    BTC tool name: pricing.get_quote
    """
    call_date = _today(on)
    
    # Exact-SKU pricing must also work for a discontinued product so callers
    # can explain historical ownership and its successor. Catalog search still
    # hides discontinued products by default.
    product_res = db_client.search_products(sku=sku, include_discontinued=True)
    if not product_res["items"]:
        return {"error": "product_not_found"}

    product = product_res["items"][0]
    base_sku = product.get("sku")
    list_price = int(product.get("list_price_vnd", 0))
    if sku != base_sku:
        requested_variant = next(
            (
                variant
                for variant in product.get("variants") or []
                if variant.get("variant_sku") == sku
            ),
            None,
        )
        if requested_variant:
            list_price += int(requested_variant.get("price_delta") or 0)
    category = product.get("category", "")

    skus_in_basket = list(basket_skus or [])
    if sku not in skus_in_basket:
        skus_in_basket.append(sku)
    # Promotion targeting is about the item being quoted. A variant inherits
    # its product's base-SKU promotions, but another basket item's promotion
    # must not discount this item.
    eligible_skus = {sku}
    if isinstance(base_sku, str) and base_sku:
        eligible_skus.add(base_sku)

    customer = db_client.get_pricing_customer_context(
        customer_phone=customer_phone,
        customer_id=customer_id,
    )
    region = customer.get("region")
    owned_skus = set(customer.get("owned_skus") or [])
    used_promos = set(customer.get("used_promos") or [])

    def applies(promo: dict[str, Any]) -> bool:
        targets = promo.get("applies_to") or []
        if "*" in targets:
            return True
        for target in targets:
            if target in eligible_skus:
                return True
            if isinstance(target, str) and target.startswith("category:"):
                expected = target.split(":", 1)[1]
                if category == expected or category.startswith(expected + "/"):
                    return True
        return False

    def discount_value(promo: dict[str, Any]) -> int:
        promo_type = promo.get("type")
        if promo_type == "fixed":
            return min(list_price, int(promo.get("discount_vnd") or 0))
        if promo_type in {"percent", "percent_second_item"}:
            return int(list_price * int(promo.get("discount_percent") or 0) / 100)
        return 0

    def public_promo(promo: dict[str, Any], discount: int) -> dict[str, Any]:
        value = {
            "promo_code": promo.get("promo_code"),
            "type": promo.get("type"),
            "discount_vnd": discount,
        }
        if promo.get("gift_sku"):
            value["gift_sku"] = promo["gift_sku"]
        return value

    active_eligible: list[tuple[dict[str, Any], int]] = []
    expired_promos: list[str] = []
    ineligible_promos: list[dict[str, str]] = []
    requested_variant = next(
        (
            variant
            for variant in product.get("variants") or []
            if variant.get("variant_sku") == sku
        ),
        {},
    )
    basket_quantity = max(qty, len(skus_in_basket))

    for promo in db_client.get_promotions():
        if not applies(promo):
            continue
        start_date = promo.get("start_date")
        end_date = promo.get("end_date")
        if end_date and call_date > end_date:
            expired_promos.append(str(promo.get("promo_code")))
            continue
        if start_date and call_date < start_date:
            continue

        conditions = promo.get("conditions") or {}
        reason = None
        required_region = conditions.get("region")
        if required_region and region not in required_region:
            reason = "region"
        required_qty = int(conditions.get("min_qty") or 0)
        if not reason and required_qty and basket_quantity < required_qty:
            reason = "min_qty"
        required_owned_sku = conditions.get("requires_owned_sku")
        if not reason and required_owned_sku and required_owned_sku not in owned_skus:
            reason = "requires_owned_sku"
        excluded_sizes = {
            str(value) for value in conditions.get("exclude_variant_size") or []
        }
        if (
            not reason
            and excluded_sizes
            and str(requested_variant.get("size")) in excluded_sizes
        ):
            reason = "excluded_variant_size"
        if (
            not reason
            and conditions.get("once_per_customer")
            and promo.get("promo_code") in used_promos
        ):
            reason = "once_per_customer"
        min_order = int(promo.get("min_order_vnd") or 0)
        if not reason and min_order and list_price * qty < min_order:
            reason = "min_order_vnd"

        if reason:
            ineligible_promos.append(
                {"promo_code": str(promo.get("promo_code")), "reason": reason}
            )
            continue
        active_eligible.append((promo, discount_value(promo)))

    stackable = [item for item in active_eligible if item[0].get("stackable")]
    exclusive = [item for item in active_eligible if not item[0].get("stackable")]
    selected_exclusive = max(exclusive, key=lambda item: item[1], default=None)
    selected = [*stackable]
    if selected_exclusive:
        selected.append(selected_exclusive)

    discount = sum(value for _, value in stackable)
    if selected_exclusive:
        discount += selected_exclusive[1]
    final_price = max(0, list_price - discount)
    applied_promos = [public_promo(promo, value) for promo, value in selected]
    not_applied_exclusive = [
        str(promo.get("promo_code"))
        for promo, _ in exclusive
        if selected_exclusive is not None and promo is not selected_exclusive[0]
    ]
    freeship = (final_price * qty) >= 1_500_000 or any(
        promo.get("type") == "freeship" for promo, _ in selected
    )

    return {
        "sku": sku,
        "list_price_vnd": list_price,
        "final_price_vnd": final_price,
        "applied_promos": applied_promos,
        "expired_promos": expired_promos,
        "ineligible_promos": ineligible_promos,
        "not_applied_exclusive": not_applied_exclusive,
        "freeship": freeship,
    }

TOOLS = {
    "catalog.search": catalog_search,
    "inventory.check": inventory_check,
    "pricing.get_quote": pricing_get_quote,
}
