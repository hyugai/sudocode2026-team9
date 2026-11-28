"""Confirmed business mutations for DeepAgent turns."""

from __future__ import annotations

import re
import json
import hashlib
from collections import Counter
from datetime import datetime
from typing import Any

from telesale_agent.core.basket import declines_order_creation
from telesale_agent.core.models import TurnContext
from telesale_agent.application.customer_text import is_closing_turn
from telesale_agent.application.tools.protocol import (
    canonical_tool_args as _canonical_tool_args,
    canonical_tool_name as _canonical_tool_name,
    decode_tool_result as _decode_tool_result,
)
from telesale_agent.application.deepagent.context.order import (
    _basket_skus,
    _basket_lines,
    _customer_phone,
    _delivery_address,
    _known_variant_sku,
    _latest_verified_sku,
    _orchestrated_result,
    _payment_method,
    _quantity,
    _requested_exchange_sku,
    _single_order,
    accepted_checkout_price,
    checkout_progress,
    checkout_requested,
    declines_exchange,
    exchange_continues,
    requests_exchange,
)
from telesale_agent.application.deepagent.context.callback import (
    callback_confirmation,
    declines_callback,
    pending_callback_slots,
    handle_message_followup,
    requested_callback_at,
    verified_callback_at,
)
from telesale_agent.application.conversation.tool_policy import is_medical_handoff_request
from telesale_agent.core.business_time import business_date


def _clip_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


class MutationToolExecutor:
    """Execute confirmed business mutations using an explicit tool registry."""

    def __init__(self, mcp_tools: dict[str, Any]) -> None:
        self.mcp_tools = mcp_tools

    async def execute(
        self,
        context: TurnContext,
        allowed_tools: frozenset[str],
        verified_calls: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], frozenset[str]]:
        """Execute an explicit, fully specified customer mutation once.

        Routing and arguments come from the current confirmation plus verified
        CRM/tool data and durable file memory. Exploratory questions never enter
        this path. The resulting call is still recorded and persisted exactly
        like a model-issued tool call, while avoiding a fragile extra model
        decision about whether to invoke an already selected business action.
        """
        remaining = set(allowed_tools)
        calls: list[dict[str, Any]] = []
        text = (context.input.text or "").casefold()
        call_date = context.input.metadata.get("call_date")
        context.state.working_memory.pop("order_create_duplicate_prevented", None)

        async def invoke(name: str, args: dict[str, Any]) -> None:
            tool = self.mcp_tools.get(name)
            if tool is None:
                return
            try:
                raw_result = await tool.ainvoke(args)
                result = _decode_tool_result(raw_result)
            except Exception as exc:
                result = {"error": str(exc)}
            canonical_name = _canonical_tool_name(name)
            calls.append(
                {
                    "id": f"orchestrated-{len(calls) + 1}",
                    "name": canonical_name,
                    "args": _canonical_tool_args(canonical_name, args),
                    "result": result,
                }
            )
            remaining.discard(name)
            if canonical_name in {"order.create", "order.update"}:
                # A write (including an uncertain/failed attempt) makes cached
                # prices, promotion eligibility and order lookups stale.
                context.state.working_memory.pop("read_tool_cache", None)

        memory = context.state.working_memory
        memory.pop("callback_reply", None)
        slots = pending_callback_slots(context)
        if declines_callback(context.input.text, context=context):
            memory.pop("pending_callback", None)
            memory.pop("pending_message_followup", None)
        elif slots is not None:
            if slots.get("date") and slots["date"] < business_date(call_date).isoformat():
                slots["date"] = None
            callback_at = requested_callback_at(slots)
            known_phone = _customer_phone(context)
            phone = (
                known_phone if re.fullmatch(r"\+?\d{8,15}", known_phone or "")
                else slots.get("phone") or memory.get("callback_phone")
            )
            missing = [
                label for value, label in (
                    (slots.get("date"), "ngày"),
                    (slots.get("time"), "giờ"),
                    (phone, "số điện thoại"),
                ) if not value
            ]
            if missing:
                memory["pending_callback"] = slots
                memory["callback_reply"] = (
                    f"Dạ, anh/chị cho bên em xin {' và '.join(missing)} để hẹn gọi lại được không ạ?"
                )
            elif callback_at and phone:
                memory.pop("pending_callback", None)
                completed = memory.setdefault("completed_callbacks", {}).setdefault(phone, {})
                result = completed.get(callback_at)
                if not verified_callback_at(result) and "mcp_schedule_callback" in self.mcp_tools:
                    args: dict[str, Any] = {
                        "customer_phone": phone,
                        "callback_at": callback_at,
                        "note": _clip_text(context.input.text, 240),
                    }
                    if call_date:
                        args["on"] = call_date
                    await invoke("mcp_schedule_callback", args)
                    result = calls[-1]["result"]
                if actual := verified_callback_at(result):
                    completed[callback_at] = result
                    if slots.get("phone"):
                        memory["callback_phone"] = phone
                    memory["callback_reply"] = callback_confirmation(result, actual)
                else:
                    memory["callback_reply"] = (
                        "Dạ, bên em chưa xác nhận được lịch gọi lại. Anh/chị có thể yêu cầu đặt lại lịch ạ."
                    )
        elif followup := handle_message_followup(context):
            memory["callback_reply"] = followup
        # Scheduling is identity/time bound and must never fall back to model-
        # invented arguments or retry after a deterministic attempt.
        remaining.discard("mcp_schedule_callback")

        if declines_order_creation(context.input.text or ""):
            memory.pop("pending_order", None)
            memory.pop("checkout_price_reference_vnd", None)
        pending_order_state = memory.get("pending_order")
        closing_checkout = bool(
            is_closing_turn(context)
            and isinstance(pending_order_state, dict)
            and pending_order_state.get("checkout_confirmed")
        )
        if "create_new_order" in remaining and (
            checkout_requested(context) or checkout_progress(context) or closing_checkout
        ):
            pending_order = memory.get("pending_order") or {}
            accepted_price = accepted_checkout_price(context) or pending_order.get("accepted_price_vnd")
            address = _delivery_address(context)
            payment = _payment_method(context)
            remembered_basket = _basket_skus(context)
            single_sku = None if pending_order.get("needs_variant") else (
                pending_order.get("sku")
                or _latest_verified_sku(verified_calls)
                or _known_variant_sku(context)
            )
            target_skus = remembered_basket or ([single_sku] if single_sku else [])
            names = {}
            for call in verified_calls:
                if call.get("name") == "catalog.search" and isinstance(call.get("result"), dict):
                    names.update({item["sku"]: item["name"] for item in call["result"].get("items", [])
                                  if isinstance(item, dict) and item.get("sku") and item.get("name")})
            requested = _basket_lines(context, target_skus, names)
            quantity = _quantity(context)
            phone = _customer_phone(context)
            customer_id = context.identity.customer_id if context.identity else None
            memory = context.state.working_memory
            created_orders = memory.setdefault("created_orders", {})
            if not isinstance(created_orders, dict):
                created_orders = memory["created_orders"] = {}
            completed = memory.setdefault("completed_checkouts", {})
            signature = hashlib.sha256(json.dumps({"lines": requested, "payment": payment,
                "phone": phone, "customer_id": customer_id, "address": address, "on": call_date},
                sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            previous = completed.get(signature)
            # Also read checkpoints from before per-cart duplicate tracking.
            if not completed and target_skus and all(sku in created_orders for sku in target_skus):
                previous = {sku: created_orders[sku] for sku in target_skus}
            if previous:
                memory["order_create_duplicate_prevented"] = previous
                memory.pop("pending_order", None)
                requested, target_skus = [], []
            counts = Counter()
            for line in requested:
                counts[line["sku"]] += line["qty"]
            multiple_units = sum(counts.values()) > 1
            quote = _orchestrated_result(verified_calls, "pricing.quote_order") if multiple_units else None
            units = quote.get("units", []) if isinstance(quote, dict) else []
            if not multiple_units and target_skus:
                single_quote = _orchestrated_result(verified_calls, "pricing.get_quote", sku=target_skus[0])
                if isinstance(single_quote, dict) and isinstance(single_quote.get("final_price_vnd"), (int, float)):
                    units = [{"sku": target_skus[0], "final_price_vnd": int(single_quote["final_price_vnd"]),
                              "applied_promos": single_quote.get("applied_promos", [])}]
            quoted_counts = {sku: sum(unit.get("sku") == sku for unit in units) for sku in counts}
            all_items_verified = bool(counts) and quoted_counts == counts and len(units) == sum(counts.values())
            for sku, needed in counts.items():
                stock = _orchestrated_result(verified_calls, "inventory.check", sku=sku)
                all_items_verified = all_items_verified and bool(
                    isinstance(stock, dict) and stock.get("in_stock") is True
                    and int(stock.get("qty") or 0) >= needed
                )
            price_changed = bool(
                accepted_price is not None
                and len(units) == 1
                and units[0]["final_price_vnd"] != accepted_price
            )
            created = False
            if all_items_verified and not price_changed and phone and customer_id and payment and address:
                args: dict[str, Any] = {
                    "customer_phone": phone, "customer_id": customer_id,
                    "payment_method": payment, "address": address,
                    "idempotency_key": (
                        f"{context.state.conversation_id}:"
                        f"{context.input.metadata.get('call_key', 'call')}:"
                        f"create:{','.join(target_skus)}"
                        + (f":cart:{signature[:16]}" if multiple_units else "")
                    ),
                }
                if multiple_units:
                    args["lines"] = [{"sku": unit["sku"], "qty": 1, "price_vnd": unit["final_price_vnd"]}
                                     for unit in units]
                else:
                    unit = units[0]
                    args.update(sku=unit["sku"], qty=1, price_vnd=unit["final_price_vnd"])
                    promos = unit.get("applied_promos") or []
                    promo = next((item for item in promos if item.get("discount_vnd", 0) > 0),
                                 promos[0] if promos else None)
                    if promo and promo.get("promo_code"):
                        args["promo_code"] = promo["promo_code"]
                if call_date:
                    args["on"] = call_date
                call_count = len(calls)
                await invoke("create_new_order", args)
                result = calls[-1].get("result") if len(calls) > call_count else None
                created = bool(isinstance(result, dict) and not result.get("error") and result.get("order_id"))
                if created:
                    for sku in counts:
                        created_orders[sku] = result["order_id"]
                    completed[signature] = {sku: result["order_id"] for sku in counts}
                    context.state.working_memory["last_created_order"] = {
                        "order_id": result["order_id"],
                        "lines": args.get("lines") or [
                            {"sku": args["sku"], "qty": args.get("qty", 1), "price_vnd": args.get("price_vnd")}
                        ],
                        "total_vnd": result.get("total_vnd"),
                        "address": args.get("address"),
                        "payment": args.get("payment_method"),
                        "estimated_delivery": result.get("estimated_delivery"),
                    }
                    context.state.working_memory.pop("pending_order", None)
                    memory.pop("checkout_price_reference_vnd", None)
            if not previous and not created:
                pending_payload: dict[str, Any] = {
                    "sku": target_skus[0] if len(target_skus) == 1 else None,
                    "payment": payment,
                }
                if multiple_units:
                    pending_payload["lines"] = requested
                if len(target_skus) > 1:
                    pending_payload["basket_skus"] = target_skus
                if quantity != 1:
                    pending_payload["quantity"] = quantity
                if len(units) == 1:
                    pending_payload["price_vnd"] = units[0]["final_price_vnd"]
                if accepted_price is not None:
                    pending_payload["accepted_price_vnd"] = accepted_price
                if pending_order.get("needs_variant"):
                    pending_payload["needs_variant"] = True
                if price_changed:
                    pending_payload["price_changed"] = True
                if address:
                    pending_payload["address"] = address
                pending_payload["checkout_confirmed"] = True
                context.state.working_memory["pending_order"] = pending_payload

        # order.create is a deterministic, identity-bound mutation. Never
        # expose it to the LLM after the gate above, even when confirmation or
        # identity is incomplete: model-generated phone/customer IDs are not
        # accepted as a fallback.
        remaining.discard("create_new_order")

        if declines_exchange(context.input.text):
            memory.pop("pending_exchange", None)
            memory.pop("order_update_blocker", None)
        update_confirmed = not declines_exchange(context.input.text) and (
            requests_exchange(context.input.text) or exchange_continues(context) or "làm thủ tục" in text
        )
        if "update_order" in remaining and update_confirmed:
            status_result = _orchestrated_result(
                verified_calls, "order.status"
            )
            order = _single_order(status_result)
            # Never fall back to a remembered ID after the current verified
            # lookup returned no unique order; that memory is stale/ambiguous.
            if order and context.identity and (
                not context.identity.customer_id
                or order.get("customer_id") not in {None, context.identity.customer_id}
            ):
                order = None
            order_id = order.get("order_id") if order else None
            new_sku = _requested_exchange_sku(context, owned_sku=order.get("sku")) if order else None
            stock = _orchestrated_result(
                verified_calls, "inventory.check", sku=new_sku
            )
            if new_sku and order and new_sku == order.get("sku"):
                memory.pop("pending_exchange", None)
                memory.pop("order_update_blocker", None)
            elif (
                isinstance(order_id, str)
                and order_id
                and new_sku
                and isinstance(stock, dict)
                and stock.get("in_stock") is True
            ):
                args = {
                    "order_id": order_id,
                    "action": "exchange_size",
                    "new_variant_sku": new_sku,
                    "reason": context.input.text,
                }
                if call_date:
                    args["on"] = call_date
                previous_call_count = len(calls)
                await invoke("update_order", args)
                result = calls[-1]["result"] if len(calls) > previous_call_count else None
                if isinstance(result, dict) and not result.get("error") and result.get("order_id"):
                    memory.pop("pending_exchange", None)
                    memory.pop("order_update_blocker", None)
                    memory.pop("read_tool_cache", None)
                else:
                    memory["order_update_blocker"] = "update_failed"
            elif not isinstance(order_id, str) or not order_id:
                memory["order_update_blocker"] = "order_not_found"
            elif not new_sku:
                memory["order_update_blocker"] = "variant_missing"
            else:
                memory["order_update_blocker"] = "variant_unverified"
        # Like create, updates are accepted only through the verified gate.
        remaining.discard("update_order")

        handoff_requested = is_medical_handoff_request(
            context.input.text,
            (
                context.call_brief.remembered_preferences.get("facts", {})
                if context.call_brief
                and isinstance(context.call_brief.remembered_preferences, dict)
                else {}
            ),
        )
        if "mcp_escalate_to_human" in remaining and handoff_requested:
            profile = context.state.customer_profile or {}
            facts = (
                context.call_brief.remembered_preferences.get("facts", {})
                if context.call_brief
                and isinstance(context.call_brief.remembered_preferences, dict)
                else {}
            )
            generated_at = (
                f"{call_date}T00:00:00+07:00" if call_date else datetime.now().astimezone().isoformat()
            )
            await invoke(
                "mcp_escalate_to_human",
                {"brief": {
                    "customer_id": (
                        context.identity.customer_id if context.identity else None
                    ),
                    "customer_phone": _customer_phone(context),
                    "customer_name": profile.get("name"),
                    "escalation_reason": "cau_hoi_y_te",
                    "conversation_summary": _clip_text(
                        "Khách yêu cầu tư vấn y tế ngoài phạm vi bán hàng. "
                        + (context.call_brief.summary if context.call_brief else ""), 500
                    ),
                    "product_advised": facts.get("product_advised")
                    or facts.get("variant_sku"),
                    "price_quoted_vnd": facts.get("price_quoted_vnd"),
                    "open_questions": [facts.get("medical_question") or context.input.text or "Khách cần tư vấn y tế."],
                    "facts_confirmed": facts,
                    "next_action": "Nhân viên có chuyên môn tiếp nhận và tư vấn an toàn.",
                    "generated_at": generated_at,
                }},
            )
        remaining.discard("mcp_escalate_to_human")

        return calls, frozenset(remaining)


