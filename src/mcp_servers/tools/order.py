"""Order domain tools — order.create, order.update, order.status"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from telesale_agent.tools.catalog import inventory_check, REFERENCE_DATE


def _today(on: str | None) -> date:
    return date.fromisoformat(on) if on else REFERENCE_DATE


# In-memory order store (replace with real DB in production)
_ORDERS: dict[str, dict[str, Any]] = {}

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
) -> dict[str, Any]:
    """Create a new order.

    BTC tool name: order.create
    args_match checks: sku, price_vnd (post-promo price)
    """
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

    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    call_date = _today(on)
    delivery_date = call_date + timedelta(days=3)

    _ORDERS[order_id] = {
        "order_id": order_id,
        "customer_phone": customer_phone,
        "sku": sku,
        "qty": qty,
        "price_vnd": price_vnd,
        "promo_code": promo_code,
        "payment": payment,
        "address": address,
        "status": "created",
        "created_on": call_date.isoformat(),
    }

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
    if order_id not in _ORDERS:
        return {"error": "order_not_found"}

    fee_map = {
        "exchange_size": 0,        # free size exchange per policy DT-03
        "exchange_product": 30_000, # standard re-ship fee
        "return": 0,               # free return per policy DT-07
        "update_address": 0,
    }
    fee = fee_map.get(action, 0)

    _ORDERS[order_id]["status"] = action
    if new_variant_sku:
        _ORDERS[order_id]["sku"] = new_variant_sku

    return {"order_id": order_id, "status": action, "fee_vnd": fee}


def order_status(
    order_id: str | None = None,
    customer_phone: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Get order status. M2 tool.

    BTC tool name: order.status
    """
    orders = []
    for oid, order in _ORDERS.items():
        if order_id and oid == order_id:
            orders.append(order)
        elif customer_phone and order.get("customer_phone") == customer_phone:
            orders.append(order)
    return {"orders": orders}


TOOLS = {
    "order.create": order_create,
    "order.update": order_update,
    "order.status": order_status,
}
