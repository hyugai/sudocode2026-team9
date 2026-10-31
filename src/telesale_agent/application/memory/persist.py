"""Persist one turn's canonical facts through a customer memory repository."""

from __future__ import annotations

import re
from typing import Any

from telesale_agent.core.interfaces import CustomerMemoryRepository
from telesale_agent.core.models import TurnContext
from telesale_agent.application.memory.turn_facts import (
    _explicit_delivery_address,
    _normalize_boolean,
    _tool_memory_candidates,
)


def persist_turn_memory(
    memory: CustomerMemoryRepository,
    context: TurnContext,
) -> list[dict[str, Any]]:
    customer_id = (
        context.identity.customer_id
        if context.identity and context.identity.customer_id
        else None
    )
    if not customer_id:
        context.state.memory_deltas.clear()
        return []

    # Phone numbers remain in CRM. Delivery addresses are retained as explicit
    # customer-confirmed transactional facts because later calls must be able
    # to reuse and supersede them without inventing "the old address".
    excluded_keys = {
        "address",
        "shipping_address",
        "phone",
        "customer_phone",
        # Order IDs must come from successful tool results, never a model or
        # customer-provided mapping that could overwrite verified orders.
        "order_ids_by_sku",
    }
    customer_candidates = {
        key: value
        for key, value in context.state.memory_deltas.items()
        if key not in excluded_keys
    }
    address = _explicit_delivery_address(context)
    if address:
        customer_candidates["delivery_address"] = address
    tool_candidates = _tool_memory_candidates(context)
    if any(step.plan.tool_name == "schedule.callback" for step in context.steps):
        # A requested time is not a confirmed appointment. The scheduler may
        # move it (or fail), so only its successful result may set callback_at.
        customer_candidates.pop("callback_at", None)
        if "callback_requested_at" in tool_candidates:
            customer_candidates.pop("callback_requested_at", None)
    candidates = {**tool_candidates, **customer_candidates}
    old_quote = memory.latest_fact(customer_id, "price_quoted_vnd")
    new_quote = candidates.get("price_quoted_vnd")
    if (
        isinstance(old_quote, (int, float))
        and isinstance(new_quote, (int, float))
        and old_quote != new_quote
    ):
        # Keep the previous customer-facing offer for cross-channel price
        # explanations while price_vnd and price_quoted_vnd move to the new
        # verified quote. An old promotion is never valid for a new order.
        candidates["previous_price_quoted_vnd"] = old_quote
        old_promo = memory.latest_fact(customer_id, "promo_code")
        if old_promo:
            candidates["previous_promo_code"] = old_promo
    previous_blocker = memory.latest_fact(customer_id, "blocker")
    new_blocker = candidates.get("blocker")
    if (
        isinstance(previous_blocker, str)
        and previous_blocker.startswith("chưa rõ ")
        and isinstance(new_blocker, str)
        and re.search(
            r"still considering|đang cân nhắc|chưa quyết định|chưa muốn mua|"
            r"chỉ tham khảo|để xem thêm",
            new_blocker,
            re.IGNORECASE,
        )
        and not re.search(
            r"(?:đã\s+)?hiểu\s+rồi|(?:đã\s+)?rõ\s+rồi|"
            r"không\s+còn\s+thắc\s+mắc|được\s+giải\s+đáp",
            context.input.text or "",
            re.IGNORECASE,
        )
    ):
        # Generic "still considering" does not resolve a concrete pending
        # policy question carried from the preceding call.
        candidates.pop("blocker")
    if "family_approved" in candidates:
        candidates["family_approved"] = _normalize_boolean(
            candidates["family_approved"]
        )
    turn_source = (
        f"{context.input.metadata.get('call_key', 'call')}"
        f"#turn{context.state.turn_number + 1}"
    )
    scenario_id = context.input.metadata.get("scenario_id")
    source = f"{scenario_id}:{turn_source}" if scenario_id else turn_source
    source = context.input.metadata.get("memory_source_id") or source
    writes = []
    for key, value in candidates.items():
        previous = memory.latest_fact(customer_id, key)
        if previous == value:
            continue
        operation = "supersede" if previous is not None else "set"
        memory.upsert_fact(customer_id, key, value)
        writes.append(
            {
                "key": key,
                "value": value,
                "op": operation,
                "source": source,
                "customer_id": customer_id,
                "provenance": (
                    "customer"
                    if key in customer_candidates
                    else "verified_tool"
                ),
                "previous_value": previous,
            }
        )

    context.state.memory_deltas.clear()
    context.state.customer_memory = memory.load(customer_id)
    return writes
