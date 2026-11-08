"""DeepAgent middleware and compatible business-policy exports."""
from __future__ import annotations
import json
import os
from typing import Any
from collections.abc import Awaitable, Callable
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from telesale_agent.application.conversation.tool_policy import (is_knowledge_request, is_policy_explanation_request, is_explicit_callback_request, is_medical_handoff_request, select_tools_for_turn, TelesaleAgentRuntimeContext)

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
        # tool_call_schema excludes injected ToolRuntime/InjectedToolArg fields.
        # args_schema may include non-JSON types (e.g. a stream_writer callable).
        schema = getattr(tool, "tool_call_schema", None)
        if schema is None:
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

