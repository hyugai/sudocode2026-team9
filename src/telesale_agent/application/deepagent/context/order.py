"""Resolve product, order, address, and payment evidence for a turn."""

from __future__ import annotations

import re
from typing import Any

from telesale_agent.core.address import (
    extract_explicit_delivery_address,
    looks_like_delivery_address,
)
from telesale_agent.core.basket import (
    confirms_order_creation,
    declines_order_creation,
    mentioned_catalog_items,
    product_lines,
    starts_basket_checkout,
    stated_payment_method,
)
from telesale_agent.core.models import TurnContext
from telesale_agent.application.asr_normalization import (
    _NUMBER_PHRASE, _small_integer, normalize_asr_transcript, normalize_spoken_product_size,
)
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
    if not unique and len(items) == 1 and items[0].get("sku") and not items[0].get("variant_not_matched"):
        return str(items[0]["sku"])
    return None

def _known_variant_sku(context: TurnContext, *, allow_inferred: bool = True) -> str | None:
    """Resolve a previously verified SKU without asking the model to infer it."""
    pending = context.state.working_memory.get("pending_order") or {}
    if pending.get("needs_variant"):
        return None
    if pending.get("sku"):
        return pending["sku"]
    verified = context.state.working_memory.get("verified_checkout_sku")
    if verified:
        return verified
    explicit_sku = re.search(r"\bSKU-[A-Z0-9-]+\b", literal_customer_text(context.input), re.I)
    if explicit_sku:
        return explicit_sku[0].upper()
    if allow_inferred and context.perception and isinstance(context.perception.entities, dict):
        for key in ("variant_sku", "sku"):
            value = context.perception.entities.get(key)
            if isinstance(value, str) and value:
                return value
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
    pending = context.state.working_memory.get("pending_exchange") or {}
    if pending.get("order_id"):
        return pending["order_id"]
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


def requests_order_status(text: str | None) -> bool:
    return bool(re.search(
        r"\b(?:tình trạng đơn|trạng thái đơn|(?:kiểm tra|tra cứu|xem lại)\s+(?:lại\s+|giúp\s+.{0,24})?đơn"
        r"|đơn\s+(?:hàng\s+)?[^.!?]{0,50}(?:xác nhận|xử lý|còn trong hệ thống|giao đến đâu))\b",
        text or "", re.IGNORECASE,
    ))


def declines_exchange(text: str | None) -> bool:
    return bool(re.search(r"\b(?:không|chưa|đừng|khoan|khỏi)\s+(?:muốn\s+|cần\s+)?đổi\b", text or "", re.I))


def requests_exchange(text: str | None) -> bool:
    text = text or ""
    if declines_exchange(text) or re.search(r"\b(?:nếu|khi)\s+(?:mua|đặt hàng)\b", text, re.I):
        return False
    if re.search(
        r"\b(?:(?:muốn|nhờ|giúp|hỗ trợ|làm thủ tục|tiến hành|thực hiện)\s+đổi"
        r"|đổi\s+cho\s+(?:anh|chị|em|tôi))\b", text, re.I
    ):
        return True
    return bool(re.search(r"\bđổi\s+(?:lên|xuống|sang)\s+size\b", text, re.I) and (
        "?" not in text or re.search(r"\b(?:đã|vừa)\s+(?:mua|nhận)\b", text, re.I)
    ))


def exchange_continues(context: TurnContext) -> bool:
    text = context.input.text or ""
    return bool(
        context.state.working_memory.get("pending_exchange")
        and not declines_exchange(text)
        and (_bare_exchange_size(text) or requests_order_status(text) or re.search(
            r"\b(?:làm thủ tục|đồng ý đổi|(?:OD|ORD)-?[A-Z0-9]+)\b", text, re.I
        ))
    )

def _payment_method(context: TurnContext) -> str | None:
    """Normalize the current choice before falling back to remembered payment."""
    pending = context.state.working_memory.get("pending_order") or {}
    return (
        _current_turn_payment_method(context)
        or pending.get("payment")
        or context.state.working_memory.get("checkout_payment_method")
        or _normalize_payment(_current_fact(context, "payment", "payment_method"))
    )

def _current_turn_payment_method(context: TurnContext) -> str | None:
    """Return payment only when it is explicit in the current utterance/NLU."""
    if method := stated_payment_method(context.input.text or ""):
        return method
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    return _normalize_payment(entities.get("payment") or entities.get("payment_method"))


def _normalize_payment(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    folded = value.strip().casefold()
    if folded in {"bank_transfer", "bank", "chuyển khoản", "transfer"}:
        return "bank"
    return stated_payment_method(value) or value.strip()

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

def checkout_requested(context: TurnContext) -> bool:
    text = context.input.text or ""
    return confirms_order_creation(
        text,
        has_address=_current_turn_has_delivery_address(context),
        has_payment=bool(_current_turn_payment_method(context)),
    ) or (bool(_basket_skus(context)) and starts_basket_checkout(text))


def checkout_progress(context: TurnContext) -> bool:
    if declines_order_creation(context.input.text or ""):
        return False
    pending = context.state.working_memory.get("pending_order") or {}
    return bool(pending) and pending.get("checkout_confirmed") is not False and (
        _current_turn_has_delivery_address(context, allow_bare_reply=not pending.get("address"))
        or bool(_current_turn_payment_method(context))
        or bool(selected_checkout_variant(context))
        or bool(stated_checkout_price(context))
        or _accepts_updated_checkout_price(context)
    )


def catalog_variant_options(items: list[dict[str, Any]]) -> dict[str, str]:
    return {
        variant["variant_sku"]: item.get("name") or item["sku"]
        for item in items if item.get("sku")
        for variant in (item.get("variants") or [])
        if isinstance(variant, dict) and isinstance(variant.get("variant_sku"), str)
    }


def checkout_product_options(context: TurnContext) -> dict[str, str]:
    options = context.state.working_memory.get(
        "checkout_product_options", _known_fact(context, "checkout_product_options")
    )
    return options if isinstance(options, dict) else {}


def verified_checkout_variant(context: TurnContext) -> str | None:
    """Reuse only a verified selection belonging to the current alternatives."""
    options = checkout_product_options(context)
    sku = context.state.working_memory.get("verified_checkout_sku")
    if isinstance(sku, str) and sku in options:
        return sku
    saved = _known_fact(context, "checkout_variant_sku")
    return saved if isinstance(saved, str) and saved in options else None


def selected_checkout_variant(context: TurnContext) -> str | None:
    options = checkout_product_options(context)
    text = literal_customer_text(context.input)
    exact_skus = {sku for sku in options if re.search(rf"(?<![\w-]){re.escape(sku)}(?![\w-])", text, re.I)}
    if len(exact_skus) == 1:
        return exact_skus.pop()
    names = {
        item["name"]
        for item in mentioned_catalog_items(text, [{"sku": sku, "name": name} for sku, name in options.items()])
    }
    matched = [sku for sku, name in options.items() if name in names]
    return matched[0] if len(matched) == 1 else None


def stated_checkout_price(context: TurnContext) -> int | None:
    """Read one seller price that the customer actually referred to."""
    text = normalize_asr_transcript(literal_customer_text(context.input))
    if re.search(r"\b(?:bên khác|đối thủ|shop khác|ngân sách|giá trần)\b", text):
        return None
    amounts = {
        int(re.sub(r"[.,]", "", match))
        for match in re.findall(
            r"\bgiá(?:\s+(?:giờ|hiện tại|mới))?(?:\s+là)?\s+"
            r"(\d{1,3}(?:[.,]\d{3})+|\d{5,})(?!\d|[.,]\d)",
            text,
        )
    }
    return amounts.pop() if len(amounts) == 1 else None


def accepted_checkout_price(context: TurnContext) -> int | None:
    if not (checkout_requested(context) or checkout_progress(context)):
        return None
    pending = context.state.working_memory.get("pending_order") or {}
    current = stated_checkout_price(context)
    if _accepts_updated_checkout_price(context):
        return pending["price_vnd"]
    if current is not None and (
        not pending.get("price_changed")
        or checkout_requested(context)
        or re.search(r"\b(?:đồng ý|chấp nhận)\b", literal_customer_text(context.input), re.I)
    ):
        return current
    return context.state.working_memory.get("checkout_price_reference_vnd") or pending.get("accepted_price_vnd")


def _accepts_updated_checkout_price(context: TurnContext) -> bool:
    pending = context.state.working_memory.get("pending_order") or {}
    return bool(pending.get("price_changed") and type(pending.get("price_vnd")) is int and re.fullmatch(
        r"\s*(?:(?:dạ|vâng)[, ]+)?(?:(?:em|anh|chị|tôi|mình)\s+)?"
        r"(?:đồng ý|chấp nhận)(?:\s+(?:giá mới|mức giá (?:đó|này)))?(?:\s+(?:ạ|nhé))?[.!]?\s*",
        literal_customer_text(context.input), re.I,
    ))


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
    if isinstance(value, list):
        skus = [sku.strip() for sku in value if isinstance(sku, str) and sku.strip()]
        if skus:
            return skus
    lines = _current_fact(context, "basket_lines")
    if isinstance(lines, list):
        skus = [
            line["sku"].strip()
            for line in lines
            if isinstance(line, dict) and isinstance(line.get("sku"), str) and line["sku"].strip()
        ]
        if skus:
            return skus
    pending = context.state.working_memory.get("pending_order")
    if isinstance(pending, dict):
        pending_skus = pending.get("basket_skus")
        if isinstance(pending_skus, list):
            skus = [sku.strip() for sku in pending_skus if isinstance(sku, str) and sku.strip()]
            if skus:
                return skus
        pending_lines = pending.get("lines")
        if isinstance(pending_lines, list):
            return [
                line["sku"].strip()
                for line in pending_lines
                if isinstance(line, dict) and isinstance(line.get("sku"), str) and line["sku"].strip()
            ]
    return []


def _basket_lines(
    context: TurnContext, skus: list[str] | None = None,
    names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Use per-item counts; read old repeated-SKU and quantity_each baskets too."""
    skus = skus if skus is not None else _basket_skus(context)
    previous = _known_fact(context, "basket_lines")
    pending = context.state.working_memory.get("pending_order") or {}
    if not isinstance(previous, list):
        previous = pending.get("lines", []) if isinstance(pending, dict) else []
    if not skus:
        skus = [line["sku"] for line in previous if isinstance(line, dict) and isinstance(line.get("sku"), str)]
    # Older memory represents physical units by repeating the SKU. Keep their
    # order, which also determines the winner when AIR-2ND-50 prices tie.
    if len(skus) != len(set(skus)):
        return [{"sku": sku, "qty": 1} for sku in skus]
    known_names = _current_fact(context, "basket_product_names")
    resolved_names = dict(known_names) if isinstance(known_names, dict) else {}
    resolved_names.update(names or {})
    return product_lines(literal_customer_text(context.input),
                         [{"sku": sku, "name": resolved_names.get(sku, sku)} for sku in skus],
                         previous, _quantity(context))

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
                and not call.get("_checkout_alternative")
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

_EXCHANGE_SIZE = rf"(?:xs|s|m|l|xl|xxl|{_NUMBER_PHRASE})"


def _normalize_exchange_size(value: str) -> str | None:
    value = value.casefold()
    if value in {"xs", "s", "m", "l", "xl", "xxl"}:
        return value.upper()
    if (size := _small_integer(value.split())) is not None and size > 0:
        return str(size)
    return None


def _bare_exchange_size(text: str) -> str | None:
    match = re.fullmatch(
        rf"\s*(?:(?:dạ|vâng)\s*,?\s*)?(?:size\s+)?({_EXCHANGE_SIZE})(?:\s+(?:ạ|nhé|nha))?[.!?]?\s*",
        text, re.I,
    )
    return _normalize_exchange_size(match[1]) if match else None


def requested_exchange_size(context: TurnContext) -> str | None:
    text = literal_customer_text(context.input)
    match = re.search(
        rf"\b(?:đổi|chuyển)\b[^?.!]{{0,55}}\bsang\s+(?:size\s+)?({_EXCHANGE_SIZE})\b",
        text, re.IGNORECASE,
    ) or re.search(
        rf"\b(?:đổi|chuyển)(?:\s+(?:lên|xuống))?\s+size\s+({_EXCHANGE_SIZE})\b",
        text, re.IGNORECASE,
    )
    if match and (size := _normalize_exchange_size(match[1])):
        return size
    pending = context.state.working_memory.get("pending_exchange") or {}
    if pending and (size := _bare_exchange_size(text)):
        return size
    entities = (context.perception.entities or {}) if context.perception else {}
    size = entities.get("requested_size")
    if size is None and re.search(r"\b(?:đổi|chuyển)\s+(?:lên\s+|xuống\s+)?size\b", text, re.I):
        size = entities.get("size")
    if (isinstance(size, str) and size.strip()) or (type(size) is int and size > 0):
        return str(size).strip().upper()
    return pending.get("size")


def _requested_exchange_sku(context: TurnContext, *, owned_sku: str | None = None) -> str | None:
    """Use the ordered product and color when verifying a size exchange."""
    entities = (context.perception.entities or {}) if context.perception else {}
    requested_size = requested_exchange_size(context)
    current_sku = owned_sku or _known_variant_sku(context)
    match = re.fullmatch(
        r"(?P<product>SKU-[A-Z0-9-]+)-(?P<size>\d+|XS|S|M|L|XL|XXL)-(?P<color>[A-Z]+)",
        current_sku or "",
        flags=re.IGNORECASE,
    )
    if requested_size and match:
        return f"{match['product']}-{requested_size}-{match['color']}".upper()
    target = entities.get("new_variant_sku") or _known_fact(context, "pending_variant_sku")
    if not isinstance(target, str) or not target:
        return None
    if not owned_sku:
        return target
    # A remembered target may only complete an exchange for that same item.
    target_parts = target.upper().rsplit("-", 2)
    if match and len(target_parts) == 3 and (
        target_parts[0] == match["product"].upper() and target_parts[2] == match["color"].upper()
    ):
        return target.upper()
    return None


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
    text = normalize_spoken_product_size(literal_customer_text(context.input))
    if product and not mentioned_catalog_items(
        f"{text} {context.input.text or ''}", [{"sku": "candidate", "name": str(product)}]
    ):
        # NLU can suggest search terms, but the customer must name the item.
        # Keep the literal utterance available for fuzzy catalog matching.
        product = None
    literal_size = re.search(r"\b(?:size|cỡ)\s+(\d{1,3}|xxs|xs|s|m|l|xl|xxl)\b", text, re.I)
    literal_color = re.search(r"\bmàu\s+(đen|trắng|xám|(?:xanh\s+)?navy|be)\b", text, re.I)
    if not product and literal_size and literal_color:
        category = re.search(
            r"\b(áo phao(?: lông vũ)?|áo khoác gió|giày chạy bộ|giày sneaker|giày trekking)\s+(?=(?:màu|size|cỡ)\b)",
            text, re.I,
        )
        if category:
            product = category[1]
    if not product and literal_size and literal_color and not re.search(r"\b(?:áo|giày|sneaker)\b", text, re.I):
        # The customer may first give a category and only then give the variant.
        # Use a category from the immediately preceding customer turn.
        previous = [msg.content for msg in context.state.messages if msg.role == "customer"][-2:]
        if len(previous) == 2:
            category = re.search(r"\b(?:giày chạy bộ|giày sneaker|giày trekking|áo khoác gió|áo phao)\b", previous[0], re.I)
            if category:
                product = category[0]
    if not product:
        return text
    parts = [str(product)]
    size = literal_size[1] if literal_size else entities.get("size")
    if size is not None:
        parts.append(f"size {size}")
    color = literal_color[1] if literal_color else entities.get("color")
    if color:
        parts.append(f"màu {color}")
    return " ".join(parts)

