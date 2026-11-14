"""DeepAgent tool-message normalization and trace projection.

This module contains provider/runtime-facing helpers only.  Keeping them out
of the turn pipeline makes the orchestration code independent from the exact
LangChain message representation and preserves one canonical trace format for
evaluation and memory persistence.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from telesale_agent.core.models import (
    ActionPlan,
    ActionResult,
    ActionStatus,
    AgentStep,
    Observation,
    PolicyDecision,
)


_BTC_TOOL_NAMES = {
    "retrieve_customer_profile": "crm.get_customer",
    "search_catalog": "catalog.search",
    "check_inventory": "inventory.check",
    "get_pricing_quote": "pricing.get_quote",
    "get_order_quote": "pricing.quote_order",
    "create_new_order": "order.create",
    "check_order_status": "order.status",
    "update_order": "order.update",
    "search_policy": "policy.search",
    "search_knowledge_base": "knowledge.search",
    "search_customer_memory_archive": "memory.archive_search",
    "mcp_schedule_callback": "schedule.callback",
    "mcp_escalate_to_human": "handoff.transfer",
}


def canonical_tool_name(name: str | None) -> str:
    if not name:
        return "unknown"
    return _BTC_TOOL_NAMES.get(name, name.replace("_", "."))


def canonical_tool_args(name: str, args: Any) -> dict[str, Any]:
    normalized = dict(args) if isinstance(args, dict) else {}
    if name == "schedule.callback" and isinstance(
        normalized.get("callback_at"), str
    ):
        try:
            callback_at = datetime.fromisoformat(normalized["callback_at"])
            normalized["callback_at"] = callback_at.isoformat(
                timespec=(
                    "minutes"
                    if callback_at.second == 0 and callback_at.microsecond == 0
                    else "seconds"
                )
            )
        except ValueError:
            pass
    if name == "order.create" and "payment_method" in normalized:
        normalized["payment"] = normalized.pop("payment_method")
    elif name == "handoff.transfer":
        brief = (
            dict(normalized.get("brief") or {})
            if isinstance(normalized.get("brief"), dict)
            else {}
        )
        brief.update(
            {
                key: value
                for key, value in normalized.items()
                if key != "brief" and value not in (None, "", [])
            }
        )
        normalized = {"brief": brief}
    return normalized


def compact_orchestrated_result(name: str, result: Any) -> Any:
    """Project verified tool output to the fields needed for one reply."""
    if not isinstance(result, dict):
        return result
    if result.get("error"):
        return {
            key: result[key]
            for key in (
                "error",
                "sku",
                "order_id",
                "restock_expected",
                "successor_sku",
                "expected_units",
                "total_vnd",
                "limit_vnd",
            )
            if key in result
        }
    if name == "catalog.search":
        items = []
        for item in (result.get("items") or [])[:3]:
            if not isinstance(item, dict):
                continue
            compact_item = {
                key: item[key]
                for key in (
                    "sku",
                    "name",
                    "brand",
                    "category",
                    "discontinued",
                    "successor_sku",
                )
                if item.get(key) not in (None, "", [], {})
            }
            if isinstance(item.get("attributes"), dict):
                compact_item["attributes"] = item["attributes"]
            variants = [
                {
                    key: variant[key]
                    for key in ("variant_sku", "size", "color", "price_delta")
                    if variant.get(key) not in (None, "")
                }
                for variant in (item.get("variants") or [])[:4]
                if isinstance(variant, dict)
            ]
            if variants:
                compact_item["variants"] = variants
            items.append(compact_item)
        return {"items": items}
    if name == "inventory.check":
        keys = (
            "sku",
            "found",
            "in_stock",
            "qty",
            "discontinued",
            "restock_expected",
            "successor_sku",
        )
        return {key: result[key] for key in keys if key in result}
    if name == "pricing.get_quote":
        compact = {
            key: result[key]
            for key in (
                "sku",
                "list_price_vnd",
                "final_price_vnd",
                "freeship",
            )
            if key in result
        }
        for key in (
            "applied_promos",
            "expired_promos",
            "ineligible_promos",
        ):
            values = result.get(key)
            if values:
                compact[key] = values[:4] if isinstance(values, list) else values
        return compact
    if name in {"policy.search", "knowledge.search"}:
        chunks = []
        for chunk in (result.get("chunks") or [])[:3]:
            if not isinstance(chunk, dict):
                continue
            content = " ".join(str(chunk.get("content") or "").split())
            chunks.append(
                {
                    key: value
                    for key, value in (
                        ("content", content[:500]),
                        ("chunk_id", chunk.get("chunk_id")),
                        ("source_file", chunk.get("source_file")),
                        ("section", chunk.get("section")),
                    )
                    if value not in (None, "")
                }
            )
        return {
            key: value
            for key, value in (
                ("query", result.get("query")),
                ("as_of", result.get("as_of")),
                ("chunks", chunks),
            )
            if value not in (None, "", [])
        }
    if name == "order.status":
        order_keys = (
            "order_id",
            "sku",
            "qty",
            "price_vnd",
            "payment",
            "address",
            "status",
            "created_on",
            "exchange_count",
            "lines",
            "total_vnd",
        )
        return {
            "orders": [
                {key: order[key] for key in order_keys if key in order}
                for order in (result.get("orders") or [])[:3]
                if isinstance(order, dict)
            ]
        }
    keep = (
        "order_id",
        "status",
        "estimated_delivery",
        "fee_vnd",
        "total_vnd",
        "needs_confirmation_call",
        "price_diff_vnd",
        "refund_vnd",
        "extra_payment_vnd",
        "refund_days",
        "callback_id",
        "callback_at",
        "moved_from",
        "ticket_id",
    )
    compact = {key: result[key] for key in keep if key in result}
    return compact or result


def tool_calls_to_steps(tool_calls: list[dict[str, Any]], *, actor="DeepAgent") -> list[AgentStep]:
    steps = []
    for call in tool_calls:
        result = call.get("result")
        output = result if isinstance(result, dict) else {"value": result}
        error = output.get("error") if isinstance(output, dict) else None
        status = ActionStatus.FAILED if error else ActionStatus.EXECUTED
        plan = ActionPlan(
            action="tool_call",
            rationale=f"Tool selected by {actor}",
            tool_name=call["name"],
            arguments=call.get("args") or {},
        )
        policy = PolicyDecision(allowed=True, reason=f"Executed by {actor}")
        action_result = ActionResult(status=status, output=output, error=error)
        observation = Observation(
            summary=f"{call['name']} {'failed' if error else 'executed'}",
            events=[{"tool_call_id": call.get("id")}],
        )
        steps.append(
            AgentStep(
                plan=plan,
                policy=policy,
                action_result=action_result,
                observation=observation,
            )
        )
    return steps


def decode_tool_result(content: Any) -> Any:
    if isinstance(content, list):
        text_blocks = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and block.get("text")
        ]
        if len(text_blocks) == 1:
            return decode_tool_result(text_blocks[0])
        if text_blocks:
            return [decode_tool_result(block) for block in text_blocks]
        return content
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content


