"""Deterministic read-only orchestration for DeepAgent turns."""

from __future__ import annotations

import json
from typing import Any

from telesale_agent.core.basket import (
    is_multi_product_request,
    mentioned_catalog_items,
    stated_payment_method,
)
from telesale_agent.core.business_time import business_date
from telesale_agent.core.models import TurnContext
from telesale_agent.application.customer_text import literal_customer_text
from telesale_agent.application.price_language import stated_price_context
from telesale_agent.application.deepagent.context.facts import _known_fact
from telesale_agent.application.tools.protocol import (
    canonical_tool_args as _canonical_tool_args,
    canonical_tool_name as _canonical_tool_name,
    decode_tool_result as _decode_tool_result,
)
from telesale_agent.application.deepagent.context.order import (
    _customer_phone,
    _delivery_address,
    _basket_skus,
    _basket_lines,
    _catalog_query,
    _known_variant_sku,
    _payment_method,
    _quantity,
    _requested_exchange_sku,
    _requested_order_id,
    _single_order,
    _single_variant_sku,
    accepted_checkout_price,
    catalog_variant_options,
    checkout_product_options,
    checkout_progress,
    checkout_requested,
    declines_exchange,
    exchange_continues,
    requested_exchange_size,
    requests_exchange,
    requests_order_status,
    selected_checkout_variant,
    stated_checkout_price,
    verified_checkout_variant,
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
        context.input.metadata.pop("quote_subject_unresolved", None)
        calls: list[dict[str, Any]] = []
        call_date = context.input.metadata.get("call_date")
        order_workflow = "check_order_status" in remaining
        current_turn_sku: str | None = None
        selected_multi_skus: list[str] = []
        catalog_items: list[dict[str, Any]] = []
        read_cache = context.state.working_memory.setdefault("read_tool_cache", {})

        async def invoke(name: str, args: dict[str, Any], *, fresh=False) -> dict[str, Any] | None:
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
            if not fresh and isinstance(cached, dict):
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
            if name == "check_order_status" and context.identity and isinstance(result, dict):
                candidate_orders = result.get("orders")
                if isinstance(candidate_orders, list):
                    customer_id = context.identity.customer_id
                    result = {**result, "orders": [
                        row for row in candidate_orders
                        if customer_id and isinstance(row, dict) and row.get("customer_id") in {None, customer_id}
                    ]}
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
        checkout = "create_new_order" in remaining and (checkout_requested(context) or checkout_progress(context))
        address = _delivery_address(context)
        final_checkout = bool(checkout and address and _payment_method(context))
        if basket_order:
            if "check_inventory" in remaining:
                for basket_sku in dict.fromkeys(basket_skus):
                    inventory_args: dict[str, Any] = {"sku": basket_sku}
                    if call_date:
                        inventory_args["on"] = call_date
                    await invoke("check_inventory", inventory_args, fresh=final_checkout)

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
            if catalog_items:
                options = catalog_variant_options(catalog_items)
                memory = context.state.working_memory
                prior_skus = checkout_product_options(context) or {_known_variant_sku(context)}
                if options and not set(options).intersection(prior_skus):
                    memory.pop("checkout_price_reference_vnd", None)
                    memory.pop("verified_checkout_sku", None)
                if len(options) > 1 and not selected_multi_skus:
                    memory["checkout_product_options"] = options
                else:
                    memory["checkout_product_options"] = {}
            if current_turn_sku:
                inventory_args: dict[str, Any] = {"sku": current_turn_sku}
                if call_date:
                    inventory_args["on"] = call_date
                await invoke("check_inventory", inventory_args, fresh=final_checkout)

        pricing_args: dict[str, Any] = {}
        if call_date:
            pricing_args["on"] = call_date
        phone = _customer_phone(context)
        if phone:
            pricing_args["customer_phone"] = phone
        if context.identity and context.identity.customer_id:
            pricing_args["customer_id"] = context.identity.customer_id
        if address:
            pricing_args["address"] = address

        memory = context.state.working_memory
        stated_price = stated_checkout_price(context)
        options = checkout_product_options(context)
        pending = memory.get("pending_order") or {}
        if options or current_turn_sku or _known_variant_sku(context):
            if stated_price and not pending.get("price_changed"):
                memory["checkout_price_reference_vnd"] = stated_price
            if payment_method := stated_payment_method(context.input.text or ""):
                memory["checkout_payment_method"] = payment_method
        checkout_sku = None
        pricing = bool(remaining.intersection({"get_pricing_quote", "get_order_quote"}))
        if (checkout or (pricing and options)) and not basket_skus and not selected_multi_skus:
            explicitly_selected = current_turn_sku or selected_checkout_variant(context)
            accepted_price = accepted_checkout_price(context) if checkout else stated_price
            checkout_sku = explicitly_selected or pending.get("sku") or verified_checkout_variant(context)
            needs_variant = False
            if options and not checkout_sku:
                amount = accepted_price or pending.get("accepted_price_vnd")
                if (amount is not None or not checkout) and 2 <= len(options) <= 4:
                    saved = _known_fact(context, "checkout_option_quotes")
                    historical_matches = {
                        sku for sku, quote in saved.items()
                        if isinstance(quote, dict) and quote.get("price_vnd") == amount
                    } if amount is not None and isinstance(saved, dict) and saved.keys() == options.keys() else set()
                    quotes = {}
                    for sku in options:
                        call = await invoke(
                            "get_pricing_quote", {**pricing_args, "sku": sku, "qty": 1},
                            fresh=final_checkout or bool(historical_matches),
                        )
                        result = call.get("result") if call else None
                        if (
                            isinstance(result, dict) and not result.get("error")
                            and result.get("sku") == sku
                            and type(result.get("final_price_vnd")) is int
                        ):
                            quotes[sku] = (call, result["final_price_vnd"])
                        if call:
                            call["_checkout_alternative"] = True
                    if not checkout and quotes:
                        context.checkout_option_quotes = {
                            sku: {
                                "price_vnd": price,
                                "quoted_on": business_date(call_date).isoformat(),
                                "promo_codes": [
                                    promo["promo_code"] for promo in call["result"].get("applied_promos", [])
                                    if isinstance(promo, dict) and promo.get("promo_code")
                                ],
                            }
                            for sku, (call, price) in quotes.items()
                        }
                    if len(quotes) == len(options) and amount is not None:
                        matches = {sku for sku, (_, price) in quotes.items() if price == amount}
                        # A current offer can confirm the old SKU, but a conflict
                        # between today's prices and the remembered set needs clarification.
                        candidates = matches | historical_matches
                        if len(candidates) == 1:
                            checkout_sku = candidates.pop()
                            selected_call = quotes[checkout_sku][0]
                            selected_call.pop("_checkout_alternative", None)
                            if checkout_sku in historical_matches:
                                selected_call["prior_checkout_quote"] = saved[checkout_sku]
                            memory["verified_checkout_sku"] = checkout_sku
                needs_variant = not checkout_sku
            if checkout and (checkout_sku or needs_variant):
                memory["pending_order"] = {**pending, "sku": checkout_sku, "needs_variant": needs_variant}
            elif checkout_sku and "get_pricing_quote" in remaining:
                await invoke("get_pricing_quote", {**pricing_args, "sku": checkout_sku, "qty": 1})
                remaining.discard("get_order_quote")
            if needs_variant:
                remaining.difference_update({"check_inventory", "get_pricing_quote", "get_order_quote"})

        # On order confirmation the SKU was already established and persisted
        # by an earlier turn, so stock can be verified without asking the model
        # to repeat that choice. Exchange turns are excluded because they need
        # the newly requested variant, not the old persisted SKU.
        if (
            "check_inventory" in remaining
            and "create_new_order" in remaining
            and not basket_order
        ):
            sku = checkout_sku or _known_variant_sku(context)
            if sku:
                inventory_args = {"sku": sku}
                if call_date:
                    inventory_args["on"] = call_date
                await invoke("check_inventory", inventory_args, fresh=final_checkout)

        order = None
        exchange = "update_order" in remaining
        if declines_exchange(context.input.text):
            memory.pop("pending_exchange", None)
        if exchange and (requests_exchange(context.input.text) or exchange_continues(context)):
            pending = memory.get("pending_exchange") or {"requested": True}
            if size := requested_exchange_size(context):
                pending["size"] = size
            memory["pending_exchange"] = pending
        if "check_order_status" in remaining:
            order_id = _requested_order_id(context)
            status_call = None
            if isinstance(order_id, str) and order_id:
                status_args = {"order_id": order_id}
                if context.identity and context.identity.phone:
                    status_args["customer_phone"] = context.identity.phone
                status_call = await invoke("check_order_status", status_args, fresh=exchange)
            else:
                phone = _customer_phone(context)
                if isinstance(phone, str) and phone:
                    status_call = await invoke("check_order_status", {"customer_phone": phone}, fresh=exchange)
                    found = _single_order(status_call.get("result")) if status_call else None
                    if found and found.get("order_id") and requests_order_status(context.input.text):
                        status_call = await invoke(
                            "check_order_status", {"order_id": found["order_id"], "customer_phone": phone}
                        )
            order = _single_order(status_call.get("result")) if status_call else None
            if order and exchange and memory.get("pending_exchange"):
                memory["pending_exchange"]["order_id"] = order.get("order_id")

        if "check_inventory" in remaining and order_workflow:
            exchange_sku = _requested_exchange_sku(context, owned_sku=order.get("sku")) if order else None
            if exchange_sku:
                inventory_args = {"sku": exchange_sku}
                if call_date:
                    inventory_args["on"] = call_date
                await invoke("check_inventory", inventory_args, fresh=exchange)
            else:
                # The customer only reported a fit problem and has not chosen
                # a target size yet. Do not let the model re-check the already
                # purchased SKU or guess a replacement variant.
                remaining.discard("check_inventory")

        # A price-only follow-up can reuse the variant persisted by the prior
        # catalog/inventory turn, avoiding another model call just to choose SKU.
        pricing_tools = {"get_pricing_quote", "get_order_quote"}
        if remaining.intersection(pricing_tools):
            skus = selected_multi_skus or basket_skus
            if not skus:
                sku = checkout_sku or current_turn_sku or _known_variant_sku(context, allow_inferred=False)
                skus = [sku] if sku else []
            names = {str(item["sku"]): str(item["name"]) for item in catalog_items
                     if isinstance(item, dict) and item.get("sku") and item.get("name")}
            lines = _basket_lines(context, skus, names)
            if lines and sum(line["qty"] for line in lines) > 1:
                pricing_args["lines"] = lines
                await invoke("get_order_quote", pricing_args, fresh=final_checkout)
                remaining.discard("get_pricing_quote")
                remaining.discard("get_order_quote")
            elif lines and ("get_pricing_quote" in remaining or not checkout_sku):
                pricing_args.update(sku=lines[0]["sku"], qty=lines[0]["qty"])
                await invoke("get_pricing_quote", pricing_args, fresh=final_checkout)
                remaining.discard("get_order_quote")
            elif not lines and (
                not context.perception or context.perception.intent != "ask_product"
                or "báo giá lại" in literal_customer_text(context.input).casefold()
                or "competitor_price_vnd" in stated_price_context(literal_customer_text(context.input))
            ):
                # Prevent the model from choosing a catalog SKU based solely
                # on a competitor price or an unspecified quote request.
                remaining.difference_update(pricing_tools)
                context.input.metadata["quote_subject_unresolved"] = True

        return calls, frozenset(remaining)

