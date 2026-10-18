"""Order domain tools — order.create, order.update, order.status"""

from __future__ import annotations

import uuid
import hashlib
from datetime import date, timedelta
from typing import Any

from mcp_servers.tools.catalog import inventory_check, REFERENCE_DATE
from telesale_agent.adapters.db.client import db_client


def _today(on: str | None) -> date:
    return date.fromisoformat(on) if on else REFERENCE_DATE


COD_LIMIT_VND = 10_000_000  # >10M must use bank transfer


def order_create(
    customer_phone: str,
    sku: str,
    qty: int,
    price_vnd: int,
    promo_code: str | None = None,
    payment: str = "COD",
    address: str | None = None,
    on: str | None = None,
    idempotency_key: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a new order.

    BTC tool name: order.create
    args_match checks: sku, price_vnd (post-promo price)
    """
    if not isinstance(address, str) or not address.strip():
        return {"error": "missing_delivery_address"}

    # COD limit check
    if payment == "COD" and (price_vnd * qty) > COD_LIMIT_VND:
        return {"error": "cod_limit_exceeded"}

    # Stock check
    stock = inventory_check(sku, on)
    if not stock["in_stock"] or stock["qty"] < qty:
        return {
            "error": "out_of_stock",
            "restock_expected": stock.get("restock_expected"),
            "successor_sku": stock.get("successor_sku"),
        }

    order_id = (
        "ORD-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:8].upper()
        if idempotency_key
        else f"ORD-{uuid.uuid4().hex[:8].upper()}"
    )
    call_date = _today(on)
    delivery_date = call_date + timedelta(days=3)

    def replay_if_matching() -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        existing = db_client.find_orders(order_id=order_id)
        if not existing:
            return None
        order = existing[0]
        expected = {
            "customer_phone": customer_phone,
            "sku": sku,
            "qty": qty,
            "price_vnd": price_vnd,
            "promo_code": promo_code,
            "payment": payment,
            "address": address.strip(),
        }
        if customer_id:
            expected["customer_id"] = customer_id
        if any(order.get(key) != value for key, value in expected.items()):
            return {"error": "idempotency_conflict", "order_id": order_id}
        created_on = order.get("created_on")
        estimated = (
            (date.fromisoformat(created_on) + timedelta(days=3)).isoformat()
            if created_on
            else delivery_date.isoformat()
        )
        return {
            "order_id": order_id,
            "status": "created",
            "estimated_delivery": estimated,
            "idempotent_replay": True,
        }

    replay = replay_if_matching()
    if replay:
        return replay

    persisted = db_client.create_order(
        order_id=order_id,
        customer_phone=customer_phone,
        customer_id=customer_id,
        sku=sku,
        qty=qty,
        price_vnd=price_vnd,
        promo_code=promo_code,
        payment=payment,
        address=address.strip(),
        order_date=call_date,
    )
    if persisted.get("error"):
        if persisted["error"] == "order_id_conflict":
            replay = replay_if_matching()
            if replay:
                return replay
        return persisted

    return {
        "order_id": order_id,
        "status": "created",
        "estimated_delivery": delivery_date.isoformat(),
    }


def order_update(
    order_id: str,
    action: str,  # exchange_size | exchange_product | return | update_address
    new_variant_sku: str | None = None,
    reason: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Update an existing order (exchange, return, address change).

    BTC tool name: order.update
    """
    existing = db_client.find_orders(order_id=order_id)
    if not existing:
        return {"error": "order_not_found"}

    fee_map = {
        "exchange_size": 0,        # free size exchange per policy DT-03
        "exchange_product": 30_000, # standard re-ship fee
        "return": 0,               # free return per policy DT-07
        "update_address": 0,
    }
    if action in {"exchange_size", "exchange_product"} and not new_variant_sku:
        return {"error": "missing_new_variant_sku"}
    if new_variant_sku:
        stock = inventory_check(new_variant_sku, on)
        if not stock.get("in_stock"):
            return {"error": "new_variant_out_of_stock", **stock}

    exchange_count = int(existing[0].get("exchange_count") or 0)
    fee = 60_000 if action.startswith("exchange") and exchange_count > 0 else fee_map.get(action, 0)
    persisted = db_client.update_order(
        order_id=order_id,
        status=action,
        new_variant_sku=new_variant_sku,
        increment_exchange=action.startswith("exchange"),
    )
    if persisted.get("error"):
        return persisted

    return {"order_id": order_id, "status": action, "fee_vnd": fee}


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
