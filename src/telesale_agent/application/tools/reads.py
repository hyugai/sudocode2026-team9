"""Deterministic read-only orchestration for DeepAgent turns."""

from __future__ import annotations

import json
from typing import Any

from telesale_agent.core.basket import (
    is_multi_product_request,
    mentioned_catalog_items,
)
from telesale_agent.core.models import TurnContext
from telesale_agent.application.customer_text import literal_customer_text
from telesale_agent.application.tools.protocol import (
    canonical_tool_args as _canonical_tool_args,
    canonical_tool_name as _canonical_tool_name,
    decode_tool_result as _decode_tool_result,
)
from telesale_agent.application.deepagent.context.order import (
    _customer_phone,
    _delivery_address,
    _basket_skus,
    _catalog_query,
    _known_variant_sku,
    _quantity,
    _requested_exchange_sku,
    _requested_order_id,
    _single_variant_sku,
)


def _clip_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


class ReadToolExecutor:
    """Execute verified read-only tool chains using an explicit tool registry."""

    def __init__(self, mcp_tools: dict[str, Any]) -> None:
        self.mcp_tools = mcp_tools

    async def prefetch(
        self,
        context: TurnContext,
        allowed_tools: frozenset[str],
    ) -> tuple[list[dict[str, Any]], frozenset[str]]:
        """Execute deterministic read chains without extra model round-trips.

        DeepAgent still owns the response and every mutating business action.
        The orchestrator only collapses read-only chains whose arguments can be
        derived from verified turn context. Calls remain visible in the trace
        and are fed to the normal memory persister as AgentSteps.
        """
        remaining = set(allowed_tools)
        calls: list[dict[str, Any]] = []
        call_date = context.input.metadata.get("call_date")
        order_workflow = "check_order_status" in remaining
        current_turn_sku: str | None = None
        selected_multi_skus: list[str] = []
        read_cache = context.state.working_memory.setdefault("read_tool_cache", {})

        async def invoke(name: str, args: dict[str, Any]) -> dict[str, Any] | None:
            tool = self.mcp_tools.get(name)
            if tool is None:
                return None
            cache_key = json.dumps(
                {
                    "tool": name,
                    "args": args,
                    "call_date": call_date,
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            cached = read_cache.get(cache_key)
            if isinstance(cached, dict):
                record = {
                    "id": f"cache-{len(calls) + 1}",
                    "name": _canonical_tool_name(name),
                    "args": _canonical_tool_args(_canonical_tool_name(name), args),
                    "result": cached,
                    "_cached": True,
                }
                calls.append(record)
                remaining.discard(name)
                return record
            try:
                raw_result = await tool.ainvoke(args)
                result = _decode_tool_result(raw_result)
            except Exception as exc:
                result = {"error": str(exc)}
            record = {
                "id": f"prefetch-{len(calls) + 1}",
                "name": _canonical_tool_name(name),
                "args": _canonical_tool_args(_canonical_tool_name(name), args),
                "result": result,
            }
            calls.append(record)
            remaining.discard(name)
            if not (isinstance(result, dict) and result.get("error")):
                read_cache[cache_key] = result
            return record

        # Policy and store-rule retrieval is read-only and its arguments are
        # fully determined by the turn. Prefetching avoids an extra model/tool
        # round-trip and ensures later-call policy questions receive current
        # verified policy evidence instead of inheriting a customer's outdated claim.
        if "search_policy" in remaining:
            knowledge_args: dict[str, Any] = {
                "query": (
                    context.perception.transcript
                    if context.perception and context.perception.transcript
                    else context.input.text or ""
                ),
                "k": 3,
            }
            known_sku = _known_variant_sku(context)
            if known_sku:
                knowledge_args["product_sku"] = known_sku
            if call_date:
                knowledge_args["as_of"] = call_date
            await invoke("search_policy", knowledge_args)

        basket_skus = _basket_skus(context)
        basket_order = bool(basket_skus and "create_new_order" in remaining)
        if basket_order:
            if "check_inventory" in remaining:
                for basket_sku in basket_skus:
                    inventory_args: dict[str, Any] = {"sku": basket_sku}
                    if call_date:
                        inventory_args["on"] = call_date
                    await invoke("check_inventory", inventory_args)

        # Catalog + inventory is a deterministic dependency chain when the
        # requested size/color resolves to exactly one variant. Running it here
        # replaces search->model->inventory->model with search->inventory->model.
        if {"search_catalog", "check_inventory"}.issubset(remaining):
            catalog_args: dict[str, Any] = {
                "query": (
                    context.input.text
                    if is_multi_product_request(context.input.text or "")
                    else _catalog_query(context)
                ),
            }
            if call_date:
                catalog_args["on"] = call_date
            catalog_call = await invoke("search_catalog", catalog_args)
            catalog_result = catalog_call.get("result") if catalog_call else None
            if not (
                isinstance(catalog_result, dict) and catalog_result.get("items")
            ):
                # Let the model retry with a different query rather than making
                # a prefetch miss terminal for this turn.
                remaining.add("search_catalog")
            catalog_items = (
                catalog_result.get("items", [])
                if isinstance(catalog_result, dict)
                else []
            )
            literal_text = literal_customer_text(context.input)
            selected_items = mentioned_catalog_items(literal_text, catalog_items)
            if not selected_items and literal_text != (context.input.text or ""):
                selected_items = mentioned_catalog_items(
                    context.input.text or "", catalog_items
                )
            if 2 <= len(selected_items) <= 4:
                selected_multi_skus = [str(item["sku"]) for item in selected_items]
                for item in selected_items:
                    inventory_args: dict[str, Any] = {"sku": item["sku"]}
                    if call_date:
                        inventory_args["on"] = call_date
                    await invoke("check_inventory", inventory_args)
            current_turn_sku = (
                None if selected_multi_skus else _single_variant_sku(catalog_result)
            )
            if current_turn_sku:
                inventory_args: dict[str, Any] = {"sku": current_turn_sku}
                if call_date:
                    inventory_args["on"] = call_date
                await invoke("check_inventory", inventory_args)

        # On order confirmation the SKU was already established and persisted
        # by an earlier turn, so stock can be verified without asking the model
        # to repeat that choice. Exchange turns are excluded because they need
        # the newly requested variant, not the old persisted SKU.
        if (
            "check_inventory" in remaining
            and "create_new_order" in remaining
            and not basket_order
        ):
            sku = _known_variant_sku(context)
            if sku:
                inventory_args = {"sku": sku}
                if call_date:
                    inventory_args["on"] = call_date
                await invoke("check_inventory", inventory_args)

        if "check_order_status" in remaining:
            order_id = _requested_order_id(context)
            if isinstance(order_id, str) and order_id:
                await invoke("check_order_status", {"order_id": order_id})
            else:
                profile = context.state.customer_profile or {}
                phone = profile.get("phone") or context.input.customer_hint
                if isinstance(phone, str) and phone:
                    await invoke("check_order_status", {"customer_phone": phone})

        if "check_inventory" in remaining and order_workflow:
            exchange_sku = _requested_exchange_sku(context)
            if exchange_sku:
                inventory_args = {"sku": exchange_sku}
                if call_date:
                    inventory_args["on"] = call_date
                await invoke("check_inventory", inventory_args)
            else:
                # The customer only reported a fit problem and has not chosen
                # a target size yet. Do not let the model re-check the already
                # purchased SKU or guess a replacement variant.
                remaining.discard("check_inventory")

        # A price-only follow-up can reuse the variant persisted by the prior
        # catalog/inventory turn, avoiding another model call just to choose SKU.
        if "get_pricing_quote" in remaining or "get_order_quote" in remaining:
            skus = selected_multi_skus or basket_skus
            if not skus:
                sku = current_turn_sku or _known_variant_sku(context)
                skus = [sku] if sku else []
            quantity = 1 if len(skus) != len(set(skus)) else _quantity(context)
            pricing_args: dict[str, Any] = {}
            if call_date:
                pricing_args["on"] = call_date
            phone = _customer_phone(context)
            if phone:
                pricing_args["customer_phone"] = phone
            if context.identity and context.identity.customer_id:
                pricing_args["customer_id"] = context.identity.customer_id
            address = _delivery_address(context)
            if address:
                pricing_args["address"] = address
            if skus and (len(skus) > 1 or quantity > 1):
                pricing_args["lines"] = [{"sku": sku, "qty": quantity} for sku in skus]
                await invoke("get_order_quote", pricing_args)
                remaining.discard("get_pricing_quote")
            elif skus:
                pricing_args.update(sku=skus[0], qty=quantity)
                await invoke("get_pricing_quote", pricing_args)
            remaining.discard("get_order_quote")

        return calls, frozenset(remaining)

