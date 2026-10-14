"""Bounded, intent-aware tool orchestration for the DeepAgent runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
import os
import re
from typing import Any, TypedDict

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from telesale_agent.core.models import Perception


class TelesaleAgentRuntimeContext(TypedDict):
    """Per-invocation data consumed by tool-routing middleware."""

    allowed_tools: list[str]


_INTENT_TOOLS: dict[str, frozenset[str]] = {
    "ask_product": frozenset({"search_catalog", "check_inventory"}),
    # Policy text is retrieved by the application before DeepAgent runs. Order
    # tools are added below only when the utterance actually concerns an order.
    "ask_policy": frozenset(),
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
    facts = memory_facts if isinstance(memory_facts, dict) else {}
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
    if any(word in text for word in ("còn hàng", "tồn kho", "size", "màu")):
        selected.add("check_inventory")
        if not exchange_signal:
            selected.add("search_catalog")
    order_negated = bool(
        re.search(
            r"\b(?:chưa|không|đừng)\b[^.!?]{0,24}"
            r"(?:lên\s+đơn|chốt(?:\s+đơn)?|đặt\s+mua|đặt\s+hàng|tạo\s+đơn|mua\s+ngay)",
            text,
        )
    )
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

    # Durable facts are routing signals, not merely prompt text. A known order
    # lets follow-up complaint/exchange turns expose the order workflow even if
    # the NLU misses a terse confirmation such as "ừ, làm thủ tục đi em".
    if facts.get("order_id") and intents.intersection({"update_order", "complain"}):
        selected.add("check_order_status")
        if update_confirmation:
            selected.add("update_order")
    if facts.get("variant_sku") and "create_order" in intents:
        selected.update({"create_new_order", "check_inventory", "get_pricing_quote"})
    if is_explicit_callback_request(text):
        selected.add("mcp_schedule_callback")
    if is_medical_handoff_request(text, facts):
        selected.add("mcp_escalate_to_human")

    return frozenset(selected)


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        value = tool.get("name")
    else:
        value = getattr(tool, "name", None)
    return value if isinstance(value, str) else None


def _request_size_estimate(request: ModelRequest[Any], tools: list[Any]) -> dict[str, int]:
    """Return a conservative local estimate without calling a tokenizer/API."""
    system_chars = len(str(getattr(request.system_message, "content", "") or ""))
    message_chars = sum(
        len(str(getattr(message, "content", "") or ""))
        for message in request.messages
    )
    tool_chars = 0
    for tool in tools:
        schema = getattr(tool, "args_schema", None)
        if hasattr(schema, "model_json_schema"):
            schema = schema.model_json_schema()
        payload = {
            "name": _tool_name(tool),
            "description": getattr(tool, "description", ""),
            "schema": schema,
        }
        tool_chars += len(json.dumps(payload, ensure_ascii=False, default=str))
    total_chars = system_chars + message_chars + tool_chars
    # Vietnamese and JSON/tool schemas are commonly denser than plain English;
    # chars/3 is intentionally conservative for a warning estimate.
    return {
        "system_chars": system_chars,
        "message_chars": message_chars,
        "tool_chars": tool_chars,
        "estimated_input_tokens": (total_chars + 2) // 3,
    }


class IntentToolRoutingMiddleware(
    AgentMiddleware[Any, TelesaleAgentRuntimeContext, Any]
):
    """Expose only the tools selected for the current application turn."""

    async def awrap_model_call(
        self,
        request: ModelRequest[TelesaleAgentRuntimeContext],
        handler: Callable[
            [ModelRequest[TelesaleAgentRuntimeContext]], Awaitable[ModelResponse[Any]]
        ],
    ) -> ModelResponse[Any]:
        context = request.runtime.context or {"allowed_tools": []}
        allowed = set(context.get("allowed_tools") or [])
        # A business tool may run at most once per DeepAgent turn. The
        # deterministic prefetch removes its tool name before the first model
        # request; this guard also removes tools already called by the model on
        # later loop iterations, preventing repeated reads and mutation retries.
        called_names = {
            str(call.get("name"))
            for message in request.messages
            for call in (getattr(message, "tool_calls", None) or [])
            if isinstance(call, dict) and call.get("name")
        }
        visible_tools = [
            tool
            for tool in request.tools
            if _tool_name(tool) in allowed and _tool_name(tool) not in called_names
        ]
        if os.environ.get("DEEPAGENT_LOG_TOKEN_ESTIMATE", "true").lower() in {
            "1",
            "true",
            "yes",
        }:
            estimate = _request_size_estimate(request, visible_tools)
            print(
                "   -> Model request estimate: "
                f"~{estimate['estimated_input_tokens']} input tokens "
                f"(system={estimate['system_chars']} chars, "
                f"messages={estimate['message_chars']} chars, "
                f"tools={estimate['tool_chars']} chars, "
                f"visible_tools={len(visible_tools)})"
            )
        return await handler(request.override(tools=visible_tools))

