"""Grounded response fallbacks for deterministic orchestration results."""

from __future__ import annotations

import re
from typing import Any

from telesale_agent.core.models import TurnContext
from telesale_agent.application.deepagent.context.order import (
    _delivery_address,
    _known_variant_sku,
    _payment_method,
)
from telesale_agent.application.deepagent.understanding.unverified_question import (
    asks_about_unresolved_question,
    unit_specific_question,
)


_CURRENT_STOCK_ASSERTION = re.compile(
    r"\b(?:hiện(?:\s+tại)?|vẫn|đang)\b[^.!?\n]{0,100}"
    r"\b(?:còn\s+hàng|có\s+sẵn\s+hàng|có\s+hàng)\b",
    re.IGNORECASE,
)


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

