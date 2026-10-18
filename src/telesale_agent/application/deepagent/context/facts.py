"""Pure projections of customer facts and compact brief selection."""

from __future__ import annotations

from typing import Any

from telesale_agent.core.models import TurnContext


def _known_fact(context: TurnContext, key: str) -> Any:
    if context.call_brief and isinstance(
        context.call_brief.remembered_preferences, dict
    ):
        facts = context.call_brief.remembered_preferences.get("facts") or {}
        if isinstance(facts, dict):
            return facts.get(key)
    return None

def _current_fact(context: TurnContext, *keys: str) -> Any:
    """Resolve a fact using current customer evidence before durable memory."""
    if context.perception:
        for source in (
            context.perception.memory_deltas,
            context.perception.entities,
        ):
            if not isinstance(source, dict):
                continue
            for key in keys:
                value = source.get(key)
                if value not in (None, "", []):
                    return value
    for key in keys:
        value = _known_fact(context, key)
        if value not in (None, "", []):
            return value
    return None

def _select_brief_facts(
    context: TurnContext,
    facts: dict[str, Any],
    limit: int = 6,
) -> list[tuple[str, Any]]:
    """Select a small intent-relevant projection of durable customer facts."""
    intents = set(context.perception.intents or []) if context.perception else set()
    if context.perception and context.perception.intent:
        intents.add(context.perception.intent)
    priorities: list[str] = []
    if intents.intersection({"create_order", "provide_info"}):
        priorities.extend(
            [
                "basket_skus",
                "basket_product_names",
                "variant_sku",
                "product_advised",
                "price_quoted_vnd",
                "delivery_address",
                "payment",
                "quantity",
                "quantity_each",
                "budget_vnd",
            ]
        )
    if "update_order" in intents:
        priorities.extend(
            [
                "order_ids_by_sku",
                "basket_product_names",
                "order_id",
                "variant_sku",
                "pending_variant_sku",
                "pending_size",
                "delivery_address",
                "size",
                "color",
            ]
        )
    price_discussion = "price_objection" in intents or any(
        phrase in (context.input.text or "").casefold()
        for phrase in ("giá", "khuyến mãi", "ưu đãi", "mã giảm", "báo giá")
    )
    if price_discussion:
        # The previous verified offer and the current offer must be visible
        # together when explaining a cross-channel price change. The default
        # six-fact budget can otherwise hide the old promotion entirely.
        priorities.extend(
            [
                "previous_price_quoted_vnd",
                "previous_promo_code",
                "price_quoted_vnd",
                "promo_code",
                "variant_sku",
                "product_advised",
            ]
        )
    if intents.intersection({"ask_product", "price_objection"}):
        priorities.extend(
            [
                "unresolved_question",
                "product_advised",
                "variant_sku",
                "price_quoted_vnd",
                "promo_code",
                "previous_price_quoted_vnd",
                "previous_promo_code",
                "basket_skus",
                "basket_product_names",
                "budget_vnd",
                "room_area_m2",
                "has_children",
            ]
        )
    if "end_call" in intents:
        priorities.extend(
            [
                "callback_at",
                "blocker",
                "product_advised",
                "price_quoted_vnd",
                "delivery_address",
                "payment",
            ]
        )
    if "complain" in intents:
        priorities.extend(
            ["order_ids_by_sku", "basket_product_names", "order_id", "owned_sku", "variant_sku", "product_advised"]
        )
    priorities.extend(
        [
            "order_ids_by_sku",
            "order_id",
            "unresolved_question",
            "basket_skus",
            "basket_product_names",
            "variant_sku",
            "product_advised",
            "delivery_address",
            "payment",
            "price_quoted_vnd",
            "promo_code",
            "previous_price_quoted_vnd",
            "previous_promo_code",
            "callback_at",
            "blocker",
            "family_approved",
        ]
    )
    selected: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for key in priorities:
        value = facts.get(key)
        if key not in seen and value not in (None, "", []):
            selected.append((key, value))
            seen.add(key)
            if len(selected) >= limit:
                return selected
    for key, value in reversed(list(facts.items())):
        if key not in seen and value not in (None, "", []):
            selected.append((key, value))
            seen.add(key)
            if len(selected) >= limit:
                break
    return selected

