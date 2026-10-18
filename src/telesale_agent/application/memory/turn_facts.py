"""Project verified customer and tool evidence into canonical memory facts."""

from __future__ import annotations

import re
from typing import Any

from telesale_agent.core.address import (
    extract_explicit_delivery_address,
    looks_like_delivery_address,
)
from telesale_agent.core.basket import mentioned_catalog_items
from telesale_agent.core.models import TurnContext
from telesale_agent.application.customer_text import literal_customer_text


_APPAREL_VARIANT = re.compile(
    r"^(?P<product>SKU-[A-Z0-9-]+)-(?P<size>\d+|S|M|L|XL)-(?P<color>[A-Z]+)$",
    re.IGNORECASE,
)


def _variant_facts(sku: Any) -> dict[str, Any]:
    if not isinstance(sku, str) or not sku:
        return {}
    match = _APPAREL_VARIANT.fullmatch(sku)
    if not match:
        return {"product_advised": sku}
    size_value = match.group("size")
    return {
        "product_advised": match.group("product").upper(),
        "variant_sku": sku.upper(),
        "size": int(size_value) if size_value.isdigit() else size_value.upper(),
        "color": match.group("color").lower(),
    }


def _normalize_boolean(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        folded = value.strip().casefold()
        if folded in {"true", "yes", "y", "1", "có", "đồng ý", "đã đồng ý"}:
            return True
        if folded in {"false", "no", "n", "0", "không", "chưa đồng ý"}:
            return False
    return value


def _explicit_delivery_address(context: TurnContext) -> str | None:
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    for key in ("delivery_address", "shipping_address", "address"):
        value = entities.get(key)
        if isinstance(value, str) and looks_like_delivery_address(value):
            return value.strip()

    return extract_explicit_delivery_address((context.input.text or "").strip())


def _basket_memory_candidates(
    context: TurnContext,
    catalog_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the latest basket from catalog-grounded SKUs and customer edits."""
    if not catalog_items:
        return {}
    text = context.input.text or ""
    literal_text = literal_customer_text(context.input)
    folded = text.casefold()
    memory = context.state.customer_memory or {}
    prior_facts = memory.get("facts", {}) if isinstance(memory, dict) else {}
    prior = prior_facts.get("basket_skus", []) if isinstance(prior_facts, dict) else []
    prior = [str(sku) for sku in prior if isinstance(sku, str)]
    prior_names = prior_facts.get("basket_product_names", {}) if isinstance(prior_facts, dict) else {}
    if not isinstance(prior_names, dict):
        prior_names = {}

    mentioned_items = mentioned_catalog_items(literal_text, catalog_items)
    if not mentioned_items and literal_text != text:
        mentioned_items = mentioned_catalog_items(text, catalog_items)
    mentioned_skus = [str(item["sku"]) for item in mentioned_items]
    if not mentioned_skus:
        return {}

    removed_sku = None
    swap_requested = bool(
        re.search(
            r"(?:\b(?:bỏ|hủy)\b[^.!?]{0,60}\bthay\b|"
            r"\b(?:đổi|thay)\b[^.!?]{0,80}\b(?:sang|bằng)\b)",
            folded,
        )
    )
    if prior and swap_requested:
        replacement = next((sku for sku in mentioned_skus if sku not in prior), None)
        if replacement:
            mentioned_prior = [sku for sku in mentioned_skus if sku in prior]
            removed_sku = mentioned_prior[-1] if mentioned_prior else prior[-1]
            basket = [replacement if sku == removed_sku else sku for sku in prior]
        else:
            basket = prior
    elif len(mentioned_skus) >= 2:
        basket = mentioned_skus
    else:
        return {}

    result: dict[str, Any] = {"basket_skus": basket}
    catalog_names = {
        str(item["sku"]): str(item["name"])
        for item in catalog_items
        if isinstance(item, dict) and item.get("sku") and item.get("name")
    }
    names = {
        sku: catalog_names.get(sku) or prior_names.get(sku)
        for sku in basket
        if catalog_names.get(sku) or prior_names.get(sku)
    }
    if names:
        result["basket_product_names"] = names
    result.update(
        {f"basket_item_{index}": sku for index, sku in enumerate(basket, start=1)}
    )
    if removed_sku:
        result["removed_sku"] = removed_sku
    return result


def _should_adopt_product(context: TurnContext, sku: Any) -> bool:
    """Prevent an agent-recommended alternative from becoming customer memory."""
    if not isinstance(sku, str) or not sku:
        return False
    memory = context.state.customer_memory or {}
    facts = memory.get("facts", {}) if isinstance(memory, dict) else {}
    if not isinstance(facts, dict):
        facts = {}
    current = facts.get("variant_sku") or facts.get("product_advised")
    if not current:
        return True
    if str(current).upper() == sku.upper():
        return True

    text = (context.input.text or "").casefold()
    if sku.casefold() in text:
        return True
    # Switching a remembered product requires explicit customer commitment;
    # merely looking up or suggesting an alternative is insufficient.
    return bool(
        re.search(
            r"(?:chọn|lấy|mua|chốt|đổi\s+sang|chuyển\s+sang|ưng)\b",
            text,
            re.IGNORECASE,
        )
    )


def _tool_memory_candidates(context: TurnContext) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    memory = context.state.customer_memory or {}
    facts = memory.get("facts", {}) if isinstance(memory, dict) else {}
    existing_order_ids = facts.get("order_ids_by_sku", {}) if isinstance(facts, dict) else {}
    order_ids_by_sku = dict(existing_order_ids) if isinstance(existing_order_ids, dict) else {}
    order_workflow = bool(
        context.perception
        and (
            context.perception.intent == "update_order"
            or "update_order" in (context.perception.intents or [])
        )
    )
    for step in context.steps:
        name = step.plan.tool_name
        args = step.plan.arguments or {}
        output = step.action_result.output or {}
        if isinstance(output, dict) and output.get("error"):
            # Failed tools are not authoritative evidence. In particular, an
            # unsuccessful order.update must never replace the owned variant.
            if name in {"inventory.check", "pricing.get_quote"} and output.get("error") in {
                "product_not_found",
                "variant_not_found",
                "sku_not_found",
            }:
                stale_sku = args.get("sku")
                memory = context.state.customer_memory or {}
                facts = memory.get("facts", {}) if isinstance(memory, dict) else {}
                if isinstance(facts, dict):
                    if facts.get("variant_sku") == stale_sku:
                        candidates["variant_sku"] = None
                    if facts.get("product_advised") == stale_sku:
                        candidates["product_advised"] = None
            continue
        if name == "inventory.check" and output.get("found") is False:
            stale_sku = args.get("sku")
            memory = context.state.customer_memory or {}
            facts = memory.get("facts", {}) if isinstance(memory, dict) else {}
            if isinstance(facts, dict):
                if facts.get("variant_sku") == stale_sku:
                    candidates["variant_sku"] = None
                if facts.get("product_advised") == stale_sku:
                    candidates["product_advised"] = None
            continue
        if name == "catalog.search":
            items = [
                item for item in output.get("items", []) if isinstance(item, dict)
            ]
            candidates.update(_basket_memory_candidates(context, items))
            variant_skus = [
                variant.get("variant_sku")
                for item in items
                for variant in (item.get("variants") or [])
                if isinstance(variant, dict) and variant.get("variant_sku")
            ]
            if len(set(variant_skus)) == 1:
                sku = variant_skus[0]
                if _should_adopt_product(context, sku):
                    candidates.update(_variant_facts(sku))
        elif name == "inventory.check":
            if args.get("sku"):
                if order_workflow:
                    pending = _variant_facts(args["sku"])
                    if pending.get("variant_sku"):
                        candidates["pending_variant_sku"] = pending["variant_sku"]
                        candidates["pending_size"] = pending.get("size")
                elif _should_adopt_product(context, args["sku"]):
                    candidates.update(_variant_facts(args["sku"]))
        elif name == "pricing.get_quote":
            sku = args.get("sku")
            if sku and _should_adopt_product(context, sku):
                candidates.update(_variant_facts(sku))
                if output.get("final_price_vnd") is not None:
                    candidates["price_vnd"] = output["final_price_vnd"]
                    candidates["price_quoted_vnd"] = output["final_price_vnd"]
                promos = output.get("applied_promos") or []
                if promos:
                    promo_codes = [
                        promo.get("promo_code") if isinstance(promo, dict) else promo
                        for promo in promos
                    ]
                    promo_codes = [code for code in promo_codes if code]
                    if promo_codes:
                        monetary_promo = next(
                            (
                                promo.get("promo_code")
                                for promo in promos
                                if isinstance(promo, dict)
                                and (promo.get("discount_vnd") or 0) > 0
                                and promo.get("promo_code")
                            ),
                            None,
                        )
                        candidates["promo_code"] = monetary_promo or promo_codes[0]
        elif name == "order.create":
            if args.get("sku"):
                candidates.update(_variant_facts(args["sku"]))
            if args.get("price_vnd") is not None:
                candidates["price_quoted_vnd"] = args["price_vnd"]
            if args.get("payment"):
                candidates["payment"] = args["payment"]
            order_id = output.get("order_id")
            if isinstance(order_id, str) and order_id:
                candidates["order_id"] = order_id
                sku = args.get("sku")
                if isinstance(sku, str) and sku:
                    order_ids_by_sku[sku] = order_id
                    candidates["order_ids_by_sku"] = dict(order_ids_by_sku)
        elif name == "order.status":
            orders = output.get("orders") or []
            for order in orders:
                if not isinstance(order, dict):
                    continue
                sku, order_id = order.get("sku"), order.get("order_id")
                if isinstance(sku, str) and sku and isinstance(order_id, str) and order_id:
                    order_ids_by_sku[sku] = order_id
                    candidates["order_ids_by_sku"] = dict(order_ids_by_sku)
            if len(orders) == 1 and isinstance(orders[0], dict):
                order = orders[0]
                if order.get("order_id"):
                    candidates["order_id"] = order["order_id"]
                if order.get("sku"):
                    order_sku = order["sku"]
                    variant = _variant_facts(order_sku)
                    if variant.get("variant_sku"):
                        candidates.update(variant)
                    else:
                        # A historical owned product is not necessarily the
                        # product currently being advised or purchased.
                        candidates["owned_sku"] = order_sku
                if order.get("price_vnd") is not None:
                    candidates["price_quoted_vnd"] = order["price_vnd"]
                if order.get("payment"):
                    candidates["payment"] = order["payment"]
            elif len(orders) == 0:
                # A successful empty lookup invalidates a remembered order ID.
                candidates["order_id"] = None
                missing_id = args.get("order_id")
                if isinstance(missing_id, str) and missing_id:
                    remaining = {
                        sku: order_id
                        for sku, order_id in order_ids_by_sku.items()
                        if order_id != missing_id
                    }
                    if remaining != order_ids_by_sku:
                        order_ids_by_sku = remaining
                        candidates["order_ids_by_sku"] = remaining
        elif name == "order.update":
            if args.get("new_variant_sku"):
                candidates.update(_variant_facts(args["new_variant_sku"]))
                candidates["pending_variant_sku"] = None
                candidates["pending_size"] = None
            if args.get("action"):
                candidates["last_order_action"] = args["action"]
        elif name == "schedule.callback" and output.get("callback_id"):
            # callback_at from the result is the effective appointment. Keep
            # the originally requested time separately when policy moved it.
            if output.get("callback_at"):
                candidates["callback_at"] = output["callback_at"]
            if output.get("moved_from"):
                candidates["callback_requested_at"] = output["moved_from"]
    return candidates
