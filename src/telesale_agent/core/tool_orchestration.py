"""Bounded, intent-aware tool orchestration for the DeepAgent runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
import os
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
        {"update_order", "check_order_status", "check_inventory"}
    ),
    "complain": frozenset({"check_order_status", "mcp_escalate_to_human"}),
    "end_call": frozenset({"mcp_schedule_callback"}),
}


def select_tools_for_turn(
    perception: Perception | None,
    transcript: str | None,
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
    if any(word in text for word in ("giá", "giảm", "khuyến mãi", "bao nhiêu")):
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
    if any(word in text for word in ("còn hàng", "tồn kho", "size", "màu")):
        selected.add("check_inventory")
        if not exchange_signal:
            selected.add("search_catalog")
    if any(word in text for word in ("lên đơn", "chốt đơn", "đặt mua")):
        selected.add("create_new_order")
    if exchange_signal:
        selected.update({"check_order_status", "check_inventory", "update_order"})
    if any(word in text for word in ("gọi lại", "liên hệ lại", "callback")):
        selected.add("mcp_schedule_callback")

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
        visible_tools = [tool for tool in request.tools if _tool_name(tool) in allowed]
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

