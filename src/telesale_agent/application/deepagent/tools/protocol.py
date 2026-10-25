"""LangChain message extraction and compatibility exports."""
from __future__ import annotations
from typing import Any
from telesale_agent.application.tools.protocol import (canonical_tool_name, canonical_tool_args, compact_orchestrated_result, decode_tool_result, tool_calls_to_steps)

def message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def current_turn_messages(messages: list[Any]) -> list[Any]:
    """Return messages produced after the most recent user message."""
    start = 0
    for index, message in enumerate(messages):
        if getattr(message, "type", None) in {"human", "user"}:
            start = index + 1
    return messages[start:]


def extract_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    """Pair DeepAgent AI tool calls with ToolMessage results for one turn."""
    pending: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []

    for message in current_turn_messages(messages):
        tool_calls = getattr(message, "tool_calls", None) or []
        for raw_call in tool_calls:
            if not isinstance(raw_call, dict):
                continue
            call_id = str(raw_call.get("id") or f"tool-{len(ordered) + 1}")
            canonical_name = canonical_tool_name(raw_call.get("name"))
            record = {
                "id": call_id,
                "name": canonical_name,
                "args": canonical_tool_args(
                    canonical_name, raw_call.get("args") or {}
                ),
                "result": None,
            }
            pending[call_id] = record
            ordered.append(record)

        if getattr(message, "type", None) == "tool":
            call_id = str(getattr(message, "tool_call_id", "") or "")
            if call_id in pending:
                pending[call_id]["result"] = decode_tool_result(
                    getattr(message, "content", "")
                )

    return ordered
