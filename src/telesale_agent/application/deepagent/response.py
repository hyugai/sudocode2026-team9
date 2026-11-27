"""Grounded response fallbacks for deterministic orchestration results."""

from __future__ import annotations

import re
from typing import Any

from telesale_agent.core.basket import asks_basket_total, is_basket_recap_request
from telesale_agent.core.models import TurnContext
from telesale_agent.application.deepagent.context.order import (
    _basket_skus,
    _delivery_address,
    _known_variant_sku,
    _payment_method,
    checkout_progress,
    checkout_requested,
)
from telesale_agent.application.customer_text import is_closing_turn
from telesale_agent.application.deepagent.understanding.unverified_question import (
    asks_about_unresolved_question,
    unit_specific_question,
)


_CURRENT_STOCK_ASSERTION = re.compile(
    r"\b(?:hiện(?:\s+tại)?|vẫn|đang)\b[^.!?\n]{0,100}"
    r"\b(?:còn\s+hàng|có\s+sẵn\s+hàng|có\s+hàng)\b",
    re.IGNORECASE,
)
_WATER_RESISTANCE = re.compile(r"\b(?:chống nước|chống thấm)\b", re.IGNORECASE)
_ORDER_CONFIRMED = re.compile(
    r"\bđã\s+(?:tạo|lên|chốt|đặt)\s+(?:thành công\s+)?đơn\b"
    r"|\bđơn(?:\s+hàng)?\b[^.!?\n]{0,45}\bđã\s+(?:được\s+)?(?:tạo|ghi nhận|xác nhận|chốt)\b",
    re.IGNORECASE,
)


def asks_about_water_resistance(context: TurnContext) -> bool:
    return bool(_WATER_RESISTANCE.search(context.input.text or ""))


def ground_water_resistance(context: TurnContext, tool_calls: list[dict[str, Any]], response: str) -> str:
    if not asks_about_water_resistance(context):
        return response
    items = {
        item["sku"]: item for call in tool_calls if call.get("name") == "catalog.search"
        for item in (call.get("result") or {}).get("items", []) if item.get("sku")
    }
    if len(items) == 1:
        attributes = next(iter(items.values())).get("attributes") or {}
        if type(attributes.get("waterproof")) is bool:
            if attributes["waterproof"]:
                return "Dạ, thông tin sản phẩm của bên em xác nhận mẫu này có tính năng chống nước ạ."
            return "Dạ, thông tin sản phẩm của bên em xác nhận mẫu này không có tính năng chống nước ạ."
    return "Dạ, bên em chưa có thông tin xác nhận về khả năng chống nước của mẫu này. Em sẽ kiểm tra thêm ạ."


def ground_unverified_unit_question(
    context: TurnContext,
    tool_calls: list[dict[str, Any]],
    response_text: str,
) -> str:
    """Answer per-unit unknowns without inventing warehouse evidence."""
    # Do not replace a successful transactional confirmation with an
    # informational fallback. No current BTC tool verifies a specific unit's
    # serial, batch, inspection, storage, or test-run measurements.
    if any(
        call.get("name") == "order.create"
        and isinstance(call.get("result"), dict)
        and call["result"].get("order_id")
        for call in tool_calls
    ):
        return response_text

    current_question = (
        context.perception.memory_deltas.get("unresolved_question")
        if context.perception
        and isinstance(context.perception.memory_deltas, dict)
        else None
    ) or unit_specific_question(context.input.text)
    remembered_question = None
    if context.call_brief and context.call_brief.unresolved_issues:
        remembered_question = context.call_brief.unresolved_issues[0]
    elif isinstance(context.state.customer_memory, dict):
        remembered_question = (
            context.state.customer_memory.get("facts") or {}
        ).get("unresolved_question")
    if current_question:
        question = current_question
        preface = "Dạ về câu hỏi của mình"
    elif remembered_question and asks_about_unresolved_question(context.input.text):
        question = remembered_question
        preface = "Dạ em còn lưu câu hỏi lần trước"
    else:
        return response_text

    return (
        f"{preface}: “{question}”. Hiện hệ thống không có thông tin xác nhận "
        "cho đúng chiếc hàng sẽ giao, nên em chưa thể trả lời chính xác ạ."
    )


def ground_current_stock_claims(
    context: TurnContext,
    tool_calls: list[dict[str, Any]],
    response_text: str,
) -> str:
    """Suppress affirmative stock claims without current-call inventory proof."""
    scope = (
        context.state.conversation_id,
        context.input.metadata.get("call_key"),
        context.input.metadata.get("call_date"),
    )
    cache = context.state.working_memory.get("verified_stock_by_call")
    if not isinstance(cache, dict) or cache.get("scope") != scope:
        cache = {"scope": scope, "stock": {}}
        context.state.working_memory["verified_stock_by_call"] = cache
    stock = cache["stock"]
    call_date = context.input.metadata.get("call_date")
    for call in tool_calls:
        if call.get("name") != "inventory.check":
            continue
        args = call.get("args") or {}
        result = call.get("result") or {}
        if not isinstance(args, dict) or not isinstance(result, dict):
            continue
        if result.get("error") or not isinstance(result.get("in_stock"), bool):
            continue
        if call_date and args.get("on") not in (None, call_date):
            continue
        sku = args.get("sku") or result.get("sku")
        if isinstance(sku, str) and sku:
            stock[sku] = result["in_stock"]

    if not _CURRENT_STOCK_ASSERTION.search(response_text):
        return response_text
    target = _known_variant_sku(context)
    verified_available = bool(stock.get(target)) if target else (
        len(stock) == 1 and next(iter(stock.values())) is True
    )
    if target and not verified_available:
        verified_available = any(
            sku.startswith(target + "-") and available is True
            for sku, available in stock.items()
        )
    if verified_available:
        return response_text

    sentences = re.split(r"(?<=[.!?])\s+|\n+", response_text)
    grounded = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and not _CURRENT_STOCK_ASSERTION.search(sentence)
    ]
    grounded.append("Em cần kiểm tra lại tồn kho trước khi xác nhận cho mình ạ.")
    return " ".join(grounded)


def _format_vnd(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", ".") + " đồng"
    except (TypeError, ValueError):
        return ""


def _basket_product_names(context: TurnContext, tool_calls=()) -> dict[str, str]:
    preferences = (
        context.call_brief.remembered_preferences
        if context.call_brief
        and isinstance(context.call_brief.remembered_preferences, dict)
        else {}
    )
    facts = preferences.get("facts") or {}
    names = facts.get("basket_product_names") if isinstance(facts, dict) else None
    names = names if isinstance(names, dict) else {}
    verified = {
        sku: name
        for sku, name in names.items()
        if isinstance(sku, str) and isinstance(name, str) and name.strip()
    }
    for call in tool_calls:
        result = call.get("result") or {}
        if call.get("name") == "catalog.search" and isinstance(result, dict) and not result.get("error"):
            for item in result.get("items", []):
                if isinstance(item, dict) and item.get("sku") and item.get("name"):
                    verified[item["sku"]] = item["name"]
    return verified


def ground_basket_recap(
    context: TurnContext,
    tool_calls: list[dict[str, Any]],
    response_text: str,
) -> str:
    """Repeat a saved cart using exact catalog names and current verified prices."""
    if not is_basket_recap_request(context.input.text or ""):
        text = (context.input.text or "").casefold()
        asks_price = any(phrase in text for phrase in ("giá", "tổng tiền", "bao nhiêu", "khuyến mãi", "khuyến mại"))
        has_mutation = any(call.get("name") in {"order.create", "order.update"} for call in tool_calls)
        if asks_price and not has_mutation:
            # The first quote may precede durable cart memory. Ground its unit
            # prices too: a correct total does not justify invented allocation.
            names = _basket_product_names(context, tool_calls)
            call_date = context.input.metadata.get("call_date")
            for call in reversed(tool_calls):
                quote = call.get("result")
                if (call.get("name") != "pricing.quote_order" or not isinstance(quote, dict)
                        or quote.get("error") or not quote.get("units")
                        or call_date and (call.get("args") or {}).get("on") != call_date):
                    continue
                if any(unit["sku"] not in names for unit in quote["units"]):
                    continue
                lines = "\n".join(f"{index}. {names[unit['sku']]} — {_format_vnd(unit['final_price_vnd'])}"
                                  for index, unit in enumerate(quote["units"], 1))
                return ("Dạ báo giá giỏ hàng của mình gồm:\n" + lines
                        + f"\nTổng tiền: {_format_vnd(quote['total_vnd'])}.")
        return response_text
    skus = _basket_skus(context)
    names = _basket_product_names(context, tool_calls)
    if not skus or any(sku not in names for sku in skus):
        if asks_basket_total(context.input.text or ""):
            return (
                "Dạ em chưa xác minh đủ giỏ hàng và giá hiện tại, "
                "nên chưa thể báo tổng tiền chính xác ạ."
            )
        return response_text

    total = 0
    if asks_basket_total(context.input.text or ""):
        quotes: dict[str, int] = {}
        call_date = context.input.metadata.get("call_date")
        for call in reversed(tool_calls):
            args = call.get("args") or {}
            result = call.get("result") or {}
            if (call.get("name") == "pricing.quote_order" and not result.get("error")
                    and (not call_date or args.get("on") == call_date)
                    and sorted(line["sku"] for line in args.get("lines", [])) == sorted(skus)):
                items = "\n".join(f"{index}. {names[unit['sku']]} — {_format_vnd(unit['final_price_vnd'])}"
                                  for index, unit in enumerate(result["units"], 1))
                return ("Dạ giỏ hàng cuối cùng của mình gồm:\n" + items
                        + f"\nTổng tiền theo giá đã kiểm tra hôm nay là {_format_vnd(result['total_vnd'])} ạ.")
        for call in tool_calls:
            if call.get("name") != "pricing.get_quote":
                continue
            args = call.get("args") or {}
            result = call.get("result") or {}
            if not isinstance(args, dict) or not isinstance(result, dict):
                continue
            if call_date and args.get("on") != call_date:
                continue
            price = result.get("final_price_vnd")
            sku = args.get("sku")
            if (
                isinstance(sku, str)
                and sku in skus
                and isinstance(price, (int, float))
                and not isinstance(price, bool)
                and price >= 0
            ):
                quantity = args.get("qty", 1)
                if isinstance(quantity, int) and quantity > 0:
                    quotes[sku] = int(price) * quantity
        if any(sku not in quotes for sku in skus):
            item_names = "\n".join(
                f"{index}. {names[sku]}" for index, sku in enumerate(skus, 1)
            )
            return (
                "Dạ giỏ hàng cuối cùng của mình gồm:\n"
                + item_names
                + "\nEm chưa xác minh đủ giá hiện tại cho các món, "
                "nên chưa thể báo tổng tiền chính xác ạ."
            )
        total = sum(quotes[sku] for sku in skus)

    lines = [f"{index}. {names[sku]}" for index, sku in enumerate(skus, 1)]
    recap = "Dạ giỏ hàng cuối cùng của mình gồm:\n" + "\n".join(lines)
    if asks_basket_total(context.input.text or ""):
        recap += f"\nTổng tiền theo giá đã kiểm tra hôm nay là {_format_vnd(total)} ạ."
    else:
        recap += f"\nEm đã ghi nhận đúng {len(skus)} món này ạ."
    return recap


def ground_multi_item_order_confirmation(
    context: TurnContext,
    tool_calls: list[dict[str, Any]],
    response_text: str,
) -> str:
    """Confirm verified single-basket or split orders using returned IDs."""
    created = [
        call for call in tool_calls
        if call.get("name") == "order.create"
        and isinstance(call.get("result"), dict)
        and call["result"].get("order_id")
    ]
    skus = _basket_skus(context)
    names = _basket_product_names(context, tool_calls)
    if len(created) == 1 and (created[0].get("args") or {}).get("lines"):
        call = created[0]
        args, result = call["args"], call["result"]
        lines = [f"{index}. {names.get(line['sku'], line['sku'])} — {_format_vnd(line['price_vnd'])}"
                 for index, line in enumerate(args["lines"], 1)]
        confirmation = f"Dạ em đã tạo đơn {result['order_id']} cho giỏ hàng:\n" + "\n".join(lines)
        if result.get("total_vnd") is not None:
            confirmation += f"\nTổng tiền: {_format_vnd(result['total_vnd'])}."
        if args.get("address"):
            confirmation += f"\nGiao đến {args['address']}."
        if args.get("payment") or args.get("payment_method"):
            confirmation += f"\nThanh toán {args.get('payment') or args['payment_method']}."
        if result.get("estimated_delivery"):
            confirmation += f"\nDự kiến giao: {result['estimated_delivery']}."
        return confirmation
    if len(created) < 2 or len(created) != len(skus) or any(sku not in names for sku in skus):
        return response_text
    by_sku = {
        (call.get("args") or {}).get("sku"): call
        for call in created
        if isinstance(call.get("args"), dict)
    }
    if any(sku not in by_sku for sku in skus):
        return response_text
    lines = [
        f"{index}. {names[sku]} — mã đơn {by_sku[sku]['result']['order_id']}"
        for index, sku in enumerate(skus, 1)
    ]
    first_args = by_sku[skus[0]]["args"]
    address = first_args.get("address")
    payment = first_args.get("payment") or first_args.get("payment_method")
    details = []
    if address and all(by_sku[sku]["args"].get("address") == address for sku in skus):
        details.append(f"giao đến {address}")
    if payment and all(
        (by_sku[sku]["args"].get("payment") or by_sku[sku]["args"].get("payment_method")) == payment
        for sku in skus
    ):
        details.append(f"thanh toán {payment}")
    confirmation = "Dạ em đã tạo đơn cho đúng giỏ hàng cuối cùng:\n" + "\n".join(lines)
    if details:
        confirmation += "\nThông tin: " + ", ".join(details) + "."
    delivery_dates = {
        by_sku[sku]["result"].get("estimated_delivery") for sku in skus
    }
    if len(delivery_dates) == 1:
        delivery_date = next(iter(delivery_dates))
        if isinstance(delivery_date, str) and delivery_date:
            confirmation += f"\nDự kiến giao: {delivery_date}."
    return confirmation


def ground_checkout_response(context: TurnContext, tool_calls: list[dict[str, Any]], response: str) -> str:
    """Report the recorded order outcome and ask only for missing checkout data."""
    for call in tool_calls:
        result = call.get("result") or {}
        args = call.get("args") or {}
        if call.get("name") == "order.create" and result.get("order_id") and not result.get("error"):
            if args.get("lines"):
                return response  # The existing cart readback lists its constituent lines.
            total = _format_vnd(result.get("total_vnd", args.get("price_vnd")))
            reply = f"Dạ, bên em đã tạo đơn {result['order_id']} ạ."
            if total:
                reply += f" Tổng tiền: {total}."
            if args.get("address"):
                reply += f" Giao đến {args['address']}."
            if args.get("payment"):
                reply += f" Thanh toán: {args['payment']}."
            return reply
    memory = context.state.working_memory
    if duplicates := memory.get("order_create_duplicate_prevented"):
        order_ids = ", ".join(dict.fromkeys(duplicates.values()))
        return f"Dạ, bên em đã có đơn {order_ids} cho yêu cầu này ạ."
    pending = memory.get("pending_order") or {}
    unverified_confirmation = bool(_ORDER_CONFIRMED.search(response)) and not (
        (memory.get("last_created_order") or {}).get("order_id")
        or any(call.get("name") == "order.status" and (call.get("result") or {}).get("orders") for call in tool_calls)
    )
    in_checkout = pending.get("checkout_confirmed") and (
        checkout_requested(context) or checkout_progress(context) or is_closing_turn(context)
    )
    if not in_checkout and not unverified_confirmation:
        return response
    if not pending:
        return "Dạ, bên em chưa xác nhận được đơn hàng này trên hệ thống ạ."
    if is_closing_turn(context):
        return "Dạ, đơn của mình chưa được tạo. Em cảm ơn anh/chị đã liên hệ ạ."
    if pending.get("needs_variant") or not (pending.get("sku") or pending.get("lines")):
        return "Dạ, anh/chị cho em xin phiên bản sản phẩm chính xác để em hoàn tất đơn ạ?"
    if pending.get("price_changed"):
        price = _format_vnd(pending["price_vnd"])
        return f"Dạ, giá hiện tại là {price}. Anh/chị có đồng ý đặt hàng với mức giá này không ạ?"
    missing = []
    if not _delivery_address(context):
        missing.append("địa chỉ giao hàng")
    if not _payment_method(context):
        missing.append("phương thức thanh toán")
    if missing:
        return "Dạ để hoàn tất đơn, mình cho em xin " + " và ".join(missing) + " ạ?"
    if any(
        call.get("name") == "inventory.check"
        and (call.get("args") or {}).get("sku") == pending.get("sku")
        and (call.get("result") or {}).get("in_stock") is False
        for call in tool_calls
    ):
        return "Dạ, phiên bản mình chọn đang hết hàng nên bên em chưa tạo đơn ạ."
    return "Dạ, bên em chưa xác nhận được đơn hàng này trên hệ thống ạ."


def _safe_fallback_response(
    context: TurnContext,
    tool_calls: list[dict[str, Any]],
) -> str:
    """Produce a grounded customer response when the model returns no text."""
    for call in reversed(tool_calls):
        result = call.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        name = call.get("name")
        if name == "order.create" and result.get("order_id"):
            return (
                f"Dạ em đã tạo đơn thành công, mã đơn là {result['order_id']}. "
                "Thông tin giao hàng đã được ghi nhận ạ."
            )
        if name == "order.update" and result.get("order_id"):
            return (
                f"Dạ em đã cập nhật đơn {result['order_id']} thành công theo "
                "yêu cầu của mình ạ."
            )
        if name == "schedule.callback" and result.get("callback_at"):
            return f"Dạ em đã ghi nhận lịch gọi lại vào {result['callback_at']} ạ."
        if name == "handoff.transfer" and result.get("ticket_id"):
            return (
                "Dạ nội dung này cần người phụ trách chuyên môn hỗ trợ. "
                "Em đã chuyển đầy đủ thông tin để mình không phải trình bày lại ạ."
            )
        if name == "pricing.get_quote" and result.get("final_price_vnd") is not None:
            price = _format_vnd(result["final_price_vnd"])
            return f"Dạ giá hiện tại đã được hệ thống xác nhận là {price} ạ."
        if name == "inventory.check" and result.get("in_stock") is not None:
            if result.get("in_stock"):
                return "Dạ sản phẩm hiện đang còn hàng ạ."
            restock = result.get("restock_expected")
            return (
                f"Dạ sản phẩm hiện tạm hết hàng, dự kiến nhập lại vào {restock} ạ."
                if restock
                else "Dạ sản phẩm hiện tạm hết hàng và chưa có lịch nhập lại ạ."
            )

    pending = context.state.working_memory.get("pending_order")
    if isinstance(pending, dict) and pending:
        missing = []
        if not _delivery_address(context):
            missing.append("địa chỉ giao hàng")
        if not _payment_method(context):
            missing.append("phương thức thanh toán")
        if missing:
            return "Dạ để hoàn tất đơn, mình cho em xin " + " và ".join(missing) + " ạ?"
    if context.state.working_memory.get("order_update_blocker") == "order_not_found":
        return (
            "Dạ em chưa tìm thấy đơn phù hợp từ thông tin đã xác minh. "
            "Mình cho em xin mã đơn khác để em kiểm tra tiếp ạ?"
        )
    return "Dạ em đã ghi nhận yêu cầu của mình. Em sẽ hỗ trợ theo thông tin đã xác minh ạ."

