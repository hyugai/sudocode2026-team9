"""Bounded, intent-aware tool orchestration for the DeepAgent runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
import os
import re
from typing import Any, NotRequired, TypedDict


from telesale_agent.core.basket import (
    asks_basket_total,
    declines_order_creation,
    is_basket_recap_request,
    is_multi_product_request,
    starts_basket_checkout,
)
from telesale_agent.core.models import Perception
from telesale_agent.application.deepagent.understanding.policy_intent import deferred_policy_topic


class TelesaleAgentRuntimeContext(TypedDict):
    """Per-invocation data consumed by tool-routing middleware."""

    allowed_tools: list[str]
    customer_id: NotRequired[str | None]


_INTENT_TOOLS: dict[str, frozenset[str]] = {
    "ask_product": frozenset({"search_catalog", "check_inventory"}),
    "ask_policy": frozenset({"search_policy"}),
    "price_objection": frozenset({"get_pricing_quote"}),
    "create_order": frozenset(
        {"create_new_order", "get_pricing_quote", "check_inventory"}
    ),
    "update_order": frozenset(
        {"check_order_status", "check_inventory"}
    ),
    "complain": frozenset({"check_order_status"}),
    "end_call": frozenset(),
}


def is_knowledge_request(transcript: str | None) -> bool:
    """Catch policy/shipping questions even when intent classification misses."""
    text = (transcript or "").casefold()
    phrases = (
        "chính sách",
        "quy định",
        "điều khoản",
        "điều lệ",
        "điều kiện khuyến mãi",
        "thể lệ khuyến mãi",
        "điều kiện voucher",
        "điều kiện đổi",
        "đổi trả",
        "đổi size",
        "đổi màu",
        "hoàn tiền",
        "bảo hành",
        "phí đổi",
        "phí ship",
        "phí giao",
        "vận chuyển",
        "giao hàng mất",
        "bao lâu nhận",
        "bao nhiêu ngày",
        "bài cũ",
        "hết hiệu lực",
    )
    return any(phrase in text for phrase in phrases) or bool(
        re.search(r"\bđổi\s+trong\s+\d+\s+ngày\b", text)
    )


def is_policy_explanation_request(transcript: str | None) -> bool:
    """Return true for informational policy questions, not exchange actions."""
    text = (transcript or "").casefold()
    return any(
        phrase in text
        for phrase in (
            "chính sách",
            "quy định",
            "điều khoản",
            "điều lệ",
            "điều kiện khuyến mãi",
            "thể lệ khuyến mãi",
            "điều kiện voucher",
            "điều kiện đổi",
            "đổi trả",
            "phí đổi",
            "phí ship",
            "phí giao",
            "vận chuyển",
            "giao hàng mất",
            "bảo hành",
            "hoàn tiền",
            "bao nhiêu ngày",
            "bài cũ",
            "hết hiệu lực",
            "lần đầu",
        )
    ) or bool(re.search(r"\bđổi\s+trong\s+\d+\s+ngày\b", text))


def is_explicit_callback_request(transcript: str | None) -> bool:
    """Distinguish a new callback request from "I am calling back" history."""
    text = (transcript or "").casefold()
    if not any(phrase in text for phrase in ("gọi lại", "liên hệ lại", "hẹn gọi")):
        return False
    customer_is_caller = re.search(
        r"\b(?:chị|anh|tôi|mình)\s+(?:đã\s+)?(?:gọi|liên\s+hệ)\s+lại"
        r"(?:\s+(?:chuyện|theo|về|như))?",
        text,
    )
    agent_is_caller = re.search(
        r"(?:\b(?:em|shop|bên\s+em)\s+(?:hãy\s+)?(?:gọi|liên\s+hệ)\s+lại\b|"
        r"\b(?:gọi|liên\s+hệ)\s+lại\s+cho\s+(?:chị|anh|tôi|mình)\b|"
        r"\bhẹn\s+(?:em|shop|bên\s+em)?\s*gọi\b)",
        text,
    )
    # Vietnamese customers commonly omit the object in an imperative such as
    # "gọi lại lúc 10 giờ ngày ...".  A concrete future time makes that form
    # unambiguous, while "chị gọi lại chuyện hôm trước" remains call history.
    timed_bare_imperative = bool(
        re.search(
            r"(?:gọi|liên\s+hệ)\s+lại[^.!?]{0,50}"
            r"(?:\d{1,2}\s*(?::\s*\d{2}|giờ)|20\d{2}-\d{2}-\d{2})",
            text,
        )
    )
    return bool(agent_is_caller or timed_bare_imperative) and not (
        customer_is_caller and not re.search(r"\b(?:em|shop|bên\s+em)\b", text)
    )


def is_medical_handoff_request(
    transcript: str | None,
    memory_facts: dict[str, Any] | None = None,
) -> bool:
    """Allow human transfer only for an explicit, safety-relevant request."""
    text = (transcript or "").casefold()
    transfer_requested = bool(
        re.search(
            r"(?:chuyển|nối)\s+(?:cho\s+)?(?:người|nhân\s*viên|bộ\s+phận|"
            r"chuyên\s*viên)|người\s+phụ\s+trách",
            text,
        )
    )
    facts = memory_facts if isinstance(memory_facts, dict) else {}
    medical_context = bool(
        re.search(
            r"(?:thuốc\s+kê\s+đơn|liều\s+thuốc|bệnh|sức\s+khỏe|y\s+tế|"
            r"chẩn\s+đoán|điều\s+trị|bác\s+sĩ)",
            text,
        )
        or facts.get("medical_question")
        or "sức khỏe" in str(facts.get("blocker", "")).casefold()
    )
    return transfer_requested and medical_context


def select_tools_for_turn(
    perception: Perception | None,
    transcript: str | None,
    memory_facts: dict[str, Any] | None = None,
) -> frozenset[str]:
    """Return the smallest safe tool set for one customer turn.

    Intent routing is primary. Small keyword guards cover NLU misses for the
    operational actions where omitting a tool would be worse than exposing one
    extra schema. The router never executes a tool; it only controls which
    schemas the DeepAgent can see for this invocation.
    """

    intents = set(perception.intents or []) if perception else set()
    if perception and perception.intent:
        intents.add(perception.intent)

    selected: set[str] = set()
    for intent in intents:
        selected.update(_INTENT_TOOLS.get(intent, ()))

    text = (transcript or "").casefold()
    if any(phrase in text for phrase in (
        "lần trước", "trước đây", "hồi trước", "bữa trước", "đợt trước",
        "cuộc gọi trước", "hôm trước", "tuần trước", "tháng trước",
        "đã từng", "lịch sử", "tôi đã nói", "tôi đã hỏi",
    )):
        selected.add("search_customer_memory_archive")
    facts = memory_facts if isinstance(memory_facts, dict) else {}
    if facts.get("basket_skus") and asks_basket_total(transcript or ""):
        # Current-call prices must be verified before repeating a cart total.
        selected.add("get_pricing_quote")
    if is_knowledge_request(text):
        selected.add("search_policy")
    if any(
        word in text
        for word in (
            "giá",
            "giảm",
            "khuyến mãi",
            "ưu đãi",
            "áp mã",
            "mã giảm",
            "voucher",
            "báo giá",
            "bao nhiêu",
        )
    ) or re.search(
        r"\b\d[\d.,]*(?:\s+\d{3})*\s*(?:(?:đồng|vnd|đ)\b|₫)",
        text,
    ):
        selected.add("get_pricing_quote")
    exchange_signal = any(
        word in text
        for word in (
            "đổi size",
            "đổi lên",
            "đổi xuống",
            "đổi hàng",
            "trả hàng",
            "hủy đơn",
            "thủ tục đổi",
            "hơi chật",
            "hơi rộng",
        )
    )
    update_confirmation = any(
        phrase in text
        for phrase in (
            "làm thủ tục đổi",
            "thực hiện đổi",
            "đổi cho anh",
            "đổi cho chị",
            "tiến hành đổi",
        )
    ) or ("làm thủ tục" in text and "update_order" in intents)
    basket_swap = bool(facts.get("basket_skus")) and bool(
        re.search(
            r"(?:\b(?:bỏ|hủy)\b[^.!?]{0,60}\bthay\b|"
            r"\b(?:đổi|thay)\b[^.!?]{0,80}\b(?:sang|bằng)\b)",
            text,
        )
    )
    if is_multi_product_request(transcript or ""):
        # Resolve both named products even if NLU labels the turn as generic
        # conversation. A missing first-turn basket cannot be recovered later.
        selected.update({"search_catalog", "check_inventory"})
    if any(word in text for word in ("còn hàng", "tồn kho", "size", "màu")):
        selected.add("check_inventory")
        if not exchange_signal:
            selected.add("search_catalog")
    order_negated = declines_order_creation(transcript or "")
    qty_unit_pattern = (
        r"(?:\d+|một|hai|ba|bốn|năm)\s*"
        r"(?:chiếc|cái|bộ|sản\s*phẩm|máy|đôi|hộp|bình|gói|cuộn|cây|áo|quần)"
    )
    purchase_confirmation = bool(
        re.search(
            rf"\b(?:mua|lấy|chốt|đặt)\s+(?:cho\s+(?:anh|chị|em|tôi)\s+)?"
            rf"{qty_unit_pattern}\b",
            text,
        )
    ) or bool(
        re.search(rf"\b{qty_unit_pattern}\b", text)
        and any(
            p in text
            for p in ("chấp nhận", "đồng ý", "lấy luôn", "mua luôn", "chốt")
        )
    )
    has_explicit_address = bool(
        re.search(
            r"(?:địa\s*chỉ(?:\s+(?:giao|nhận)\s+hàng)?\s*(?:là|:)?|"
            r"(?:giờ\s+)?giao(?:\s+(?:đến|về|qua|tới))?(?:\s+cho\s+(?:anh|chị|em|tôi))?)\s+"
            r"(?:số\s+)?\d+",
            text,
        )
    )
    has_explicit_payment = bool(
        re.search(r"\b(?:cod\b|chuyển\s*khoản|tiền\s*mặt|bank|transfer)\b", text)
    )
    if not order_negated and (
        any(
            word in text
            for word in ("lên đơn", "chốt đơn", "đặt mua", "đặt hàng", "tạo đơn")
        )
        or purchase_confirmation
        or (has_explicit_address and has_explicit_payment)
        or (
            any(p in text for p in ("chấp nhận", "đồng ý"))
            and (has_explicit_address or has_explicit_payment)
        )
    ):
        selected.add("create_new_order")
        selected.update({"check_inventory", "get_pricing_quote"})
    if facts.get("basket_skus") and starts_basket_checkout(transcript or ""):
        # An accepted basket with quantities and a delivery address starts a
        # checkout even when payment is deferred to the next customer turn.
        selected.update({"create_new_order", "check_inventory", "get_pricing_quote"})
    if exchange_signal:
        selected.update({"check_order_status", "check_inventory"})
    if update_confirmation:
        selected.update({"check_order_status", "check_inventory", "update_order"})

    # Editing a remembered shopping basket is a catalog operation, not an
    # update of an already-created order.  Ground the replacement SKU first so
    # the durable basket can supersede the removed item.
    if basket_swap:
        selected.update({"search_catalog", "check_inventory"})
        if not re.search(
            r"\b(?:mã\s+đơn|đơn\s+(?:hàng\s+)?(?:od|ord)[-_]?[a-z0-9]+)\b",
            text,
        ):
            selected.discard("check_order_status")
            selected.discard("update_order")

    # Asking how a policy works for a prospective purchase is not an order
    # lookup. This prevents SC-031--040 from querying order.status merely
    # because the words "đổi size" appear in an informational question.
    explicit_order_reference = bool(facts.get("order_id") or facts.get("order_ids_by_sku")) or bool(
        re.search(r"\b(?:OD|ORD)-?[A-Z0-9]+\b", transcript or "", re.IGNORECASE)
    ) or any(
        phrase in text
        for phrase in ("đã nhận", "đã mua", "đơn của", "mã đơn")
    )
    if (
        is_policy_explanation_request(text)
        and not explicit_order_reference
        and not update_confirmation
    ):
        selected.discard("check_order_status")
        selected.discard("update_order")
        if "ask_product" not in intents:
            selected.discard("check_inventory")

    # Durable facts are routing signals, not merely prompt text. A known order
    # lets follow-up complaint/exchange turns expose the order workflow even if
    # the NLU misses a terse confirmation such as "ừ, làm thủ tục đi em".
    if (facts.get("order_id") or facts.get("order_ids_by_sku")) and intents.intersection({"update_order", "complain"}):
        selected.add("check_order_status")
        if update_confirmation:
            selected.add("update_order")
    if facts.get("variant_sku") and "create_order" in intents:
        selected.update({"create_new_order", "check_inventory", "get_pricing_quote"})
    if is_explicit_callback_request(text):
        selected.add("mcp_schedule_callback")
    if is_medical_handoff_request(text, facts):
        selected.add("mcp_escalate_to_human")

    # A plan to ask about policy on a later call is a memory cue, not a
    # request to spend a retrieval call now.
    if deferred_policy_topic(transcript):
        selected.discard("search_policy")

    if facts.get("basket_skus") and is_basket_recap_request(transcript or ""):
        # A saved-cart recap is not an order lookup, even when the NLU labels
        # "confirm" as an order intent. Keep genuine order-ID/status requests.
        current_order_reference = bool(
            re.search(
                r"\b(?:(?:od|ord)-?[a-z0-9]+|mã\s+đơn|đơn\s+(?:hàng\s+)?"
                r"(?:của|(?:od|ord)[-_]?[a-z0-9]+)|"
                r"đã\s+(?:đặt|mua|nhận)|trạng\s+thái\s+đơn|"
                r"tình\s+trạng\s+đơn|giao\s+(?:đến|tới)\s+đâu)\b",
                text,
            )
        )
        if not current_order_reference:
            selected.discard("check_order_status")
            selected.discard("update_order")
        selected.discard("search_catalog")
        if not any(word in text for word in ("còn hàng", "tồn kho")):
            selected.discard("check_inventory")

    if "get_pricing_quote" in selected:
        selected.add("get_order_quote")
    return frozenset(selected)


