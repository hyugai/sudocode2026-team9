"""Resolve product, order, address, and payment evidence for a turn."""

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
from telesale_agent.application.deepagent.context.facts import _current_fact, _known_fact


def _single_variant_sku(result: Any) -> str | None:
    """Return a SKU only when a catalog result resolves unambiguously."""
    if not isinstance(result, dict):
        return None
    items = [item for item in result.get("items", []) if isinstance(item, dict)]
    variants = [
        variant.get("variant_sku")
        for item in items
        for variant in (item.get("variants") or [])
        if isinstance(variant, dict) and variant.get("variant_sku")
    ]
    unique = list(dict.fromkeys(str(sku) for sku in variants))
    if len(unique) == 1:
        return unique[0]
    if not unique and len(items) == 1 and items[0].get("sku"):
        return str(items[0]["sku"])
    return None

def _known_variant_sku(context: TurnContext) -> str | None:
    """Resolve a previously verified SKU without asking the model to infer it."""
    if context.perception and isinstance(context.perception.entities, dict):
        for key in ("variant_sku", "sku"):
            value = context.perception.entities.get(key)
            if isinstance(value, str) and value:
                return value
    pending = context.state.working_memory.get("pending_order")
    if isinstance(pending, dict) and pending.get("sku"):
        return pending["sku"]
    if context.call_brief and isinstance(
        context.call_brief.remembered_preferences, dict
    ):
        facts = context.call_brief.remembered_preferences.get("facts") or {}
        if isinstance(facts, dict):
            for key in ("variant_sku", "product_advised"):
                value = facts.get(key)
                if isinstance(value, str) and value:
                    return value
    return None

def _requested_order_id(context: TurnContext) -> str | None:
    text = literal_customer_text(context.input)
    match = re.search(r"\b(?:OD|ORD)-?[A-Z0-9]+\b", text, re.IGNORECASE)
    if match:
        return match.group(0).upper()
    if context.perception:
        for source in (context.perception.entities, context.perception.memory_deltas):
            if isinstance(source, dict):
                explicit = source.get("order_id")
                if isinstance(explicit, str) and explicit:
                    return explicit

    mapping = _known_fact(context, "order_ids_by_sku")
    if isinstance(mapping, dict) and mapping:
        valid = {
            sku: order_id
            for sku, order_id in mapping.items()
            if isinstance(sku, str) and isinstance(order_id, str) and order_id
        }
        names = _known_fact(context, "basket_product_names")
        names = names if isinstance(names, dict) else {}
        catalog_items = [
            {"sku": sku, "name": name}
            for sku, name in names.items()
            if sku in valid and isinstance(name, str)
        ]
        mentioned = {
            item["sku"] for item in mentioned_catalog_items(text, catalog_items)
        }
        mentioned.update(sku for sku in valid if sku.casefold() in text.casefold())
        matched_ids = {valid[sku] for sku in mentioned}
        if len(matched_ids) == 1:
            return next(iter(matched_ids))
        if len(valid) == 1:
            return next(iter(valid.values()))
        # A generic remembered order_id is ambiguous for a multi-item cart.
        # Let the caller look up all orders by verified phone instead.
        return None

    remembered = _known_fact(context, "order_id")
    return remembered if isinstance(remembered, str) and remembered else None

def _payment_method(context: TurnContext) -> str | None:
    """Normalize the current choice before falling back to remembered payment."""
    text = (context.input.text or "").casefold()
    if "chuyển khoản" in text or re.search(r"\b(?:bank|transfer)\b", text):
        return "bank"
    if "cod" in text and not re.search(r"(?:không|khong)\s+cod", text):
        return "COD"
    value = _current_fact(context, "payment", "payment_method")
    if not isinstance(value, str) or not value.strip():
        return None
    folded = value.strip().casefold()
    if folded in {"bank_transfer", "bank", "chuyển khoản", "transfer"}:
        return "bank"
    return "COD" if folded == "cod" else value.strip()

def _current_turn_payment_method(context: TurnContext) -> str | None:
    """Return payment only when it is explicit in the current utterance/NLU."""
    text = (context.input.text or "").casefold()
    if "chuyển khoản" in text or re.search(r"\b(?:bank|transfer)\b", text):
        return "bank"
    if "cod" in text and not re.search(r"(?:không|khong)\s+cod", text):
        return "COD"
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    value = entities.get("payment") or entities.get("payment_method")
    if not isinstance(value, str) or not value.strip():
        return None
    folded = value.strip().casefold()
    if folded in {"bank_transfer", "bank", "chuyển khoản", "transfer"}:
        return "bank"
    return "COD" if folded == "cod" else value.strip()

def _current_turn_has_delivery_address(
    context: TurnContext,
    *,
    allow_bare_reply: bool = False,
) -> bool:
    """Tell current address evidence apart from an address loaded from memory."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    if any(
        isinstance(entities.get(key), str)
        and looks_like_delivery_address(entities[key])
        for key in ("delivery_address", "shipping_address", "address")
    ):
        return True
    text = (context.input.text or "").strip()
    if extract_explicit_delivery_address(text):
        return True
    return bool(allow_bare_reply and looks_like_delivery_address(text))

def _quantity(context: TurnContext) -> int:
    value = _current_fact(context, "quantity", "qty", "quantity_each")
    if isinstance(value, bool):
        return 1
    try:
        parsed = int(value)
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass
    text = (context.input.text or "").casefold()
    word_map = {"một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5}
    m = re.search(
        r"\b(\d+|một|hai|ba|bốn|năm)\s*(?:chiếc|cái|bộ|sản\s*phẩm|máy|đôi|hộp|bình|gói|cuộn|cây|áo|quần)\b",
        text,
    )
    if m:
        val = m.group(1)
        if val.isdigit():
            return int(val)
        if val in word_map:
            return word_map[val]
    pending = context.state.working_memory.get("pending_order") or {}
    if isinstance(pending.get("quantity"), int) and pending["quantity"] > 0:
        return pending["quantity"]
    return 1

def _basket_skus(context: TurnContext) -> list[str]:
    value = _current_fact(context, "basket_skus")
    if not isinstance(value, list):
        return []
    return [sku.strip() for sku in value if isinstance(sku, str) and sku.strip()]

def _customer_phone(context: TurnContext) -> str | None:
    """Return only the phone already verified by CRM/identity resolution."""
    profile = context.state.customer_profile or {}
    candidates = [
        profile.get("phone") if isinstance(profile, dict) else None,
        context.identity.phone if context.identity else None,
        context.input.customer_hint,
    ]
    return next(
        (value for value in candidates if isinstance(value, str) and value),
        None,
    )

def _delivery_address(context: TurnContext) -> str | None:
    """Resolve an explicit current-turn or CRM-verified delivery address."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    profile = context.state.customer_profile or {}
    brief_profile = (
        context.call_brief.verified_customer_data
        if context.call_brief
        and isinstance(context.call_brief.verified_customer_data, dict)
        else {}
    )
    pending = context.state.working_memory.get("pending_order") or {}
    text = (context.input.text or "").strip()
    explicit_address = extract_explicit_delivery_address(text)
    if explicit_address:
        return explicit_address
    if (
        isinstance(pending, dict)
        and pending
        and looks_like_delivery_address(text)
    ):
        # This is the direct answer to our preceding address question. Prefer
        # it over an occasionally truncated NLU entity (for example "1").
        cleaned = re.sub(
            r"^(?:địa\s*chỉ(?:\s+giao\s+hàng|\s+nhận\s+hàng)?\s*(?:là|:)?\s*)",
            "",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\s+(?:nhé|nha)(?:\s+em)?[.!]?$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        return cleaned or text
    candidates = [
        *(
            entities.get(key)
            for key in ("delivery_address", "shipping_address", "address")
            if isinstance(entities.get(key), str)
            and looks_like_delivery_address(entities[key])
        ),
        pending.get("address") if isinstance(pending, dict) else None,
        _known_fact(context, "delivery_address"),
        profile.get("address") if isinstance(profile, dict) else None,
        brief_profile.get("address"),
    ]
    address = next(
        (
            value.strip()
            for value in candidates
            if isinstance(value, str) and value.strip()
        ),
        None,
    )
    if address:
        return address

    return None

def _single_order(result: Any) -> dict[str, Any] | None:
    """Return one unambiguous order from a verified order.status result."""
    if not isinstance(result, dict):
        return None
    orders = result.get("orders") or []
    if len(orders) != 1 or not isinstance(orders[0], dict):
        return None
    return orders[0]

def _orchestrated_result(
    calls: list[dict[str, Any]],
    name: str,
    *,
    sku: str | None = None,
) -> Any:
    """Find a successful, already verified orchestration result."""
    for call in reversed(calls):
        if call.get("name") != name:
            continue
        args = call.get("args") or {}
        if sku and args.get("sku") != sku:
            continue
        result = call.get("result")
        if not (isinstance(result, dict) and result.get("error")):
            return result
    return None

def _latest_verified_sku(calls: list[dict[str, Any]]) -> str | None:
    """Prefer a SKU verified for the current turn over remembered products."""
    for preferred_name in ("pricing.get_quote", "inventory.check"):
        for call in reversed(calls):
            args = call.get("args") or {}
            result = call.get("result")
            if (
                call.get("name") == preferred_name
                and isinstance(args.get("sku"), str)
                and not (isinstance(result, dict) and result.get("error"))
            ):
                return args["sku"]
    for call in reversed(calls):
        if call.get("name") == "catalog.search":
            sku = _single_variant_sku(call.get("result"))
            if sku:
                return sku
    return None

def _requested_exchange_sku(context: TurnContext) -> str | None:
    """Derive a new apparel variant only from a verified prior SKU + new size."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    explicit = entities.get("new_variant_sku")
    if isinstance(explicit, str) and explicit:
        return explicit
    requested_size = entities.get("requested_size")
    text = context.input.text or ""
    exchange_request = bool(
        re.search(
            r"(?:đổi|chuyển|lên|xuống)[^?.!]{0,30}\bsize\s*"
            r"(?:\d+|s|m|l|xl)\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    # Prefer the destination after "sang" over the first size in the phrase.
    # In "đổi từ size 38 sang 39", the first size is the owned/source size.
    target_match = re.search(
        r"\b(?:đổi|chuyển)\b[^?.!]{0,45}\bsang\s+(?:size\s*)?"
        r"(\d+|s|m|l|xl)\b",
        text,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:lên|xuống)\s+size\s*(\d+|s|m|l|xl)\b",
        text,
        flags=re.IGNORECASE,
    )
    if target_match:
        requested_size = target_match.group(1)
    elif requested_size is None and exchange_request:
        requested_size = entities.get("size")
    if requested_size is None:
        match = (
            re.search(
                r"\bsize\s*(\d+|s|m|l|xl)\b",
                text,
                flags=re.IGNORECASE,
            )
            if exchange_request
            else None
        )
        requested_size = match.group(1) if match else None
    if requested_size is None:
        pending = _known_fact(context, "pending_variant_sku")
        return pending if isinstance(pending, str) and pending else None
    current_sku = _known_variant_sku(context)
    if requested_size is None or not current_sku:
        return None
    match = re.fullmatch(
        r"(?P<product>SKU-[A-Z0-9-]+)-(?P<size>\d+|S|M|L|XL)-(?P<color>[A-Z]+)",
        current_sku,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return (
        f"{match.group('product')}-{str(requested_size).upper()}-"
        f"{match.group('color')}"
    ).upper()

def _catalog_query(context: TurnContext) -> str:
    """Build a compact catalog query while retaining requested variant data."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    product = next(
        (
            entities.get(key)
            for key in ("product_name", "product", "name", "query")
            if entities.get(key)
        ),
        None,
    )
    if not product:
        return context.input.text or ""
    parts = [str(product)]
    if entities.get("size") is not None:
        parts.append(f"size {entities['size']}")
    if entities.get("color"):
        parts.append(f"màu {entities['color']}")
    return " ".join(parts)

