"""Order domain tools — order.create, order.update, order.status"""

from __future__ import annotations

import uuid
import hashlib
from datetime import date
from typing import Any

from mcp_servers.tools.catalog import inventory_check, pricing_get_quote, REFERENCE_DATE
from mcp_servers.tools.business_calendar import delivery_date
from mcp_servers.tools.pricing import PricingCalculator
from telesale_agent.adapters.db.client import db_client


def _today(on: str | None) -> date:
    return date.fromisoformat(on) if on else REFERENCE_DATE


COD_LIMIT_VND = 10_000_000  # >10M must use bank transfer


def order_create(
    customer_phone: str,
    sku: str | None = None,
    qty: int = 1,
    price_vnd: int | None = None,
    promo_code: str | None = None,
    payment: str = "COD",
    address: str | None = None,
    on: str | None = None,
    idempotency_key: str | None = None,
    customer_id: str | None = None,
    basket_skus: list[str] | None = None,
    lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate the server quote and persist one order with all its units."""
    if not isinstance(address, str) or not address.strip():
        return {"error": "missing_delivery_address"}
    if lines is None and not sku:
        return {"error": "missing_sku_or_lines"}
    requested = lines if lines is not None else [{"sku": sku, "qty": qty, "price_vnd": price_vnd}]
    if not requested or any(int(line.get("qty", 1)) < 1 for line in requested):
        return {"error": "invalid_quantity"}
    extra = [{"sku": item, "qty": 1} for item in basket_skus or []] if lines is None else []
    order_id = (
        "ORD-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:8].upper()
        if idempotency_key else f"ORD-{uuid.uuid4().hex[:8].upper()}"
    )
    call_date = _today(on)

    def replay_if_matching() -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        found = db_client.find_orders(order_id=order_id)
        if not found:
            return None
        existing = found[0]
        expected = {"customer_phone": customer_phone, "payment": payment, "address": address.strip()}
        expected["promo_code"] = promo_code
        if customer_id:
            expected["customer_id"] = customer_id
        stored = sorted((line["sku"], line["price_vnd"]) for line in existing["lines"]
                        for _ in range(line.get("qty", 1)))
        supplied = sorted((line["sku"], line["price_vnd"]) for line in requested
                          for _ in range(line.get("qty", 1)) if line.get("price_vnd") is not None)
        requested_skus = sorted(line["sku"] for line in requested for _ in range(line.get("qty", 1)))
        if (any(existing.get(key) != value for key, value in expected.items())
                or requested_skus != sorted(sku for sku, _ in stored)
                or supplied and stored != supplied):
            return {"error": "idempotency_conflict", "order_id": order_id}
        created_on = date.fromisoformat(existing["created_on"]) if existing.get("created_on") else call_date
        total = sum(line["price_vnd"] * line.get("qty", 1) for line in existing["lines"])
        return {"order_id": order_id, "status": "created", "total_vnd": total,
                "needs_confirmation_call": payment == "COD" and total > 2_000_000,
                "estimated_delivery": delivery_date(created_on, address), "idempotent_replay": True}

    replay = replay_if_matching()
    if replay:
        return replay
    for line in requested:
        stock = inventory_check(line["sku"], on)
        if not stock.get("in_stock") or stock.get("qty", 0) < int(line.get("qty", 1)):
            return {"error": "out_of_stock", **stock}
    same_day = [order for order in db_client.find_orders(customer_phone=customer_phone)
                if order.get("created_on") == call_date.isoformat()]
    used_today = any("AIR-2ND-50" in order.get("promos", []) for order in same_day)
    quote = PricingCalculator(db_client, call_date, customer_phone, customer_id, address).quote_order(
        [{"sku": line["sku"], "qty": line.get("qty", 1)} for line in requested] + extra,
        second_item_used=used_today, tie_prefer_first=bool(extra) and bool(same_day),
    )
    if quote.get("error"):
        return quote
    units = [unit for unit in quote["units"] if unit["line"] < len(requested)]
    wanted = sorted((line["sku"], line["price_vnd"]) for line in requested
                    for _ in range(int(line.get("qty", 1))) if line.get("price_vnd") is not None)
    actual = sorted((unit["sku"], unit["final_price_vnd"]) for unit in units)
    if wanted and wanted != actual:
        return {"error": "price_mismatch",
                "expected_units": [{"sku": unit["sku"], "price_vnd": unit["final_price_vnd"]} for unit in units],
                "given": [{"sku": item, "price_vnd": price} for item, price in wanted]}
    total = sum(unit["final_price_vnd"] for unit in units)
    if payment == "COD" and total > COD_LIMIT_VND:
        return {"error": "cod_limit_exceeded", "limit_vnd": COD_LIMIT_VND, "total_vnd": total}
    order_promos = [promo["promo_code"] for promo in quote["order_promos"]]
    persisted_lines = [
        {"sku": unit["sku"], "qty": 1, "price_vnd": unit["final_price_vnd"],
         "promos": sorted({promo["promo_code"] for promo in unit["applied_promos"]} | set(order_promos))}
        for unit in units
    ]
    persisted = db_client.create_order(
        order_id=order_id, customer_phone=customer_phone, customer_id=customer_id,
        sku=units[0]["sku"], qty=len(units), price_vnd=units[0]["final_price_vnd"],
        promo_code=promo_code, payment=payment, address=address.strip(), order_date=call_date,
        lines=persisted_lines,
    )
    if persisted.get("error"):
        if persisted["error"] == "order_id_conflict":
            replay = replay_if_matching()
            if replay:
                return replay
        return persisted
    return {"order_id": order_id, "status": "created", "total_vnd": total,
            "needs_confirmation_call": payment == "COD" and total > 2_000_000,
            "estimated_delivery": delivery_date(call_date, address)}


def order_update(
    order_id: str,
    action: str,
    new_variant_sku: str | None = None,
    reason: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Apply BTC exchange/return fees and return the pickup/refund details."""
    existing = db_client.find_orders(order_id=order_id)
    if not existing:
        return {"error": "order_not_found"}
    order = existing[0]
    result: dict[str, Any] = {"order_id": order_id, "action": action}
    if action in {"exchange_size", "exchange_product"}:
        if not new_variant_sku:
            return {"error": "missing_new_variant_sku"}
        stock = inventory_check(new_variant_sku, on)
        if not stock.get("in_stock"):
            return {"error": "new_variant_out_of_stock", **stock}
        quote = pricing_get_quote(new_variant_sku, on=on, customer_phone=order.get("customer_phone"))
        if quote.get("error"):
            return quote
        difference = quote["final_price_vnd"] - order["price_vnd"]
        result.update(
            new_variant_sku=new_variant_sku,
            fee_vnd=60_000 if int(order.get("exchange_count") or 0) > 0 else 0,
            price_diff_vnd=difference, refund_vnd=max(-difference, 0),
            extra_payment_vnd=max(difference, 0), refund_days="3-5 ngày làm việc",
            status="pickup_scheduled",
        )
    elif action == "return":
        result.update(reason=reason, refund_vnd=order["price_vnd"],
                      refund_days="3-5 ngày làm việc", status="pickup_scheduled")
    elif action == "update_address":
        result["status"] = "updated"
    else:
        return {"error": "unknown_action"}
    persisted = db_client.update_order(
        order_id=order_id, status=result["status"], new_variant_sku=new_variant_sku,
        increment_exchange=action.startswith("exchange"),
    )
    return persisted if persisted.get("error") else result


def order_status(
    order_id: str | None = None,
    customer_phone: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Get order status. M2 tool.

    BTC tool name: order.status
    """
    return {
        "orders": db_client.find_orders(
            order_id=order_id,
            customer_phone=customer_phone,
        )
    }


TOOLS = {
    "order.create": order_create,
    "order.update": order_update,
    "order.status": order_status,
}
