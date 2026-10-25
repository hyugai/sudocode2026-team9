"""Confirmed business mutations for DeepAgent turns."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from telesale_agent.core.basket import declines_order_creation, starts_basket_checkout
from telesale_agent.core.models import TurnContext
from telesale_agent.application.tools.protocol import (
    canonical_tool_args as _canonical_tool_args,
    canonical_tool_name as _canonical_tool_name,
    decode_tool_result as _decode_tool_result,
)
from telesale_agent.application.deepagent.context.order import (
    _basket_skus,
    _current_turn_has_delivery_address,
    _current_turn_payment_method,
    _customer_phone,
    _delivery_address,
    _known_variant_sku,
    _latest_verified_sku,
    _orchestrated_result,
    _payment_method,
    _quantity,
    _requested_exchange_sku,
    _single_order,
)
from telesale_agent.application.deepagent.context.callback import _requested_callback_at
from telesale_agent.application.conversation.tool_policy import (
    is_explicit_callback_request,
    is_medical_handoff_request,
)


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

        callback_requested = is_explicit_callback_request(context.input.text)
        if "mcp_schedule_callback" in remaining and callback_requested:
            callback_at = _requested_callback_at(context)
            phone = _customer_phone(context)
            if callback_at and phone:
                args: dict[str, Any] = {
                    "customer_phone": phone,
                    "callback_at": callback_at,
                    "note": _clip_text(context.input.text, 240),
                }
                if call_date:
                    args["on"] = call_date
                await invoke("mcp_schedule_callback", args)
        # Scheduling is identity/time bound and must never fall back to model-
        # invented arguments or retry after a deterministic attempt.
        remaining.discard("mcp_schedule_callback")

        remembered_basket = _basket_skus(context)
        if declines_order_creation(context.input.text or ""):
            context.state.working_memory.pop("pending_order", None)
        elif remembered_basket and starts_basket_checkout(context.input.text or ""):
            # This is checkout consent, not merely a remembered address. Keep
            # it only within the live conversation until payment completes.
            pending = context.state.working_memory.get("pending_order")
            pending = dict(pending) if isinstance(pending, dict) else {}
            pending.update(
                basket_skus=remembered_basket,
                address=_delivery_address(context),
                checkout_confirmed=True,
            )
            context.state.working_memory["pending_order"] = pending
        pending_order = context.state.working_memory.get("pending_order")
        address = _delivery_address(context)
        create_negated = declines_order_creation(context.input.text or "")
        qty_unit_pattern = (
            r"(?:\d+|một|hai|ba|bốn|năm)\s*"
            r"(?:chiếc|cái|bộ|sản\s*phẩm|máy|đôi|hộp|bình|gói|cuộn|cây|áo|quần)"
        )
        explicit_address = _current_turn_has_delivery_address(
            context,
            allow_bare_reply=bool(
                isinstance(pending_order, dict)
                and pending_order
                and not pending_order.get("address")
            ),
        )
        explicit_payment = _current_turn_payment_method(context)
        explicit_purchase = (
            any(
                signal in text
                for signal in (
                    "lên đơn",
                    "chốt đơn",
                    "đặt mua",
                    "đặt hàng",
                    "tạo đơn",
                )
            )
            or bool(
                re.search(
                    rf"\b(?:mua|lấy|chốt|đặt)\s+(?:cho\s+(?:anh|chị|em|tôi)\s+)?"
                    rf"{qty_unit_pattern}\b",
                    text,
                    flags=re.IGNORECASE,
                )
            )
            or bool(
                re.search(rf"\b{qty_unit_pattern}\b", text, flags=re.IGNORECASE)
                and (
                    any(
                        p in text
                        for p in (
                            "chấp nhận",
                            "đồng ý",
                            "lấy luôn",
                            "mua luôn",
                            "chốt",
                        )
                    )
                    or explicit_address
                    or explicit_payment
                )
            )
            or (
                any(p in text for p in ("chấp nhận", "đồng ý"))
                and bool(explicit_address or explicit_payment)
            )
        )
        pending_progress = bool(
            isinstance(pending_order, dict)
            and pending_order
            and (
                (not pending_order.get("address") and explicit_address)
                or (not pending_order.get("payment") and explicit_payment)
                or (pending_order.get("checkout_confirmed") and explicit_payment)
            )
        )
        create_confirmed = not create_negated and (
            explicit_purchase or pending_progress
        )
        if "create_new_order" in remaining and create_confirmed:
            pending_order = (
                pending_order if isinstance(pending_order, dict) else {}
            )
            remembered_basket = _basket_skus(context)
            single_sku = (
                pending_order.get("sku")
                or _latest_verified_sku(verified_calls)
                or _known_variant_sku(context)
            )
            target_skus = remembered_basket or ([single_sku] if single_sku else [])
            created_orders = context.state.working_memory.setdefault(
                "created_orders", {}
            )
            if not isinstance(created_orders, dict):
                created_orders = {}
                context.state.working_memory["created_orders"] = created_orders
            already_created = {
                sku: created_orders[sku]
                for sku in target_skus
                if sku in created_orders
            }
            target_skus = [sku for sku in target_skus if sku not in created_orders]
            if already_created and not target_skus:
                context.state.working_memory["order_create_duplicate_prevented"] = (
                    already_created
                )
            quantity = _quantity(context)
            payment = _payment_method(context) or pending_order.get("payment")
            phone = _customer_phone(context)
            customer_id = (
                context.identity.customer_id if context.identity else None
            )
            verified_items: list[tuple[str, int, str | None]] = []
            for sku in target_skus:
                stock = _orchestrated_result(
                    verified_calls, "inventory.check", sku=sku
                )
                quote = _orchestrated_result(
                    verified_calls, "pricing.get_quote", sku=sku
                )
                price = (
                    quote.get("final_price_vnd")
                    if isinstance(quote, dict)
                    else None
                )
                promo_code = None
                if isinstance(quote, dict):
                    promos = quote.get("applied_promos") or []
                    first_promo = next(
                        (
                            promo
                            for promo in promos
                            if isinstance(promo, dict)
                            and (promo.get("discount_vnd") or 0) > 0
                        ),
                        promos[0] if promos else None,
                    )
                    promo_code = (
                        first_promo.get("promo_code")
                        if isinstance(first_promo, dict)
                        else first_promo
                    )
                if (
                    isinstance(price, (int, float))
                    and isinstance(stock, dict)
                    and stock.get("in_stock") is True
                    and int(stock.get("qty") or 0) >= quantity
                ):
                    verified_items.append((sku, int(price), promo_code))

            all_items_verified = bool(target_skus) and (
                len(verified_items) == len(target_skus)
            )
            if (
                all_items_verified
                and phone
                and customer_id
                and payment
                and address
            ):
                all_created = True
                for sku, price, promo_code in verified_items:
                    args: dict[str, Any] = {
                        "customer_phone": phone,
                        "customer_id": customer_id,
                        "sku": sku,
                        "price_vnd": price,
                        "qty": quantity,
                        "payment_method": payment,
                        "address": address,
                        "idempotency_key": (
                            f"{context.state.conversation_id}:"
                            f"{context.input.metadata.get('call_key', 'call')}:"
                            f"create:{sku}"
                        ),
                    }
                    if isinstance(promo_code, str) and promo_code:
                        args["promo_code"] = promo_code
                    if call_date:
                        args["on"] = call_date
                    await invoke("create_new_order", args)
                    result = calls[-1].get("result")
                    succeeded = not (
                        isinstance(result, dict) and result.get("error")
                    )
                    all_created = all_created and succeeded
                    if succeeded and isinstance(result, dict):
                        created_orders[sku] = result.get("order_id") or True
                if all_created:
                    context.state.working_memory.pop("pending_order", None)
            elif target_skus:
                pending_payload: dict[str, Any] = {
                    "sku": target_skus[0] if len(target_skus) == 1 else None,
                    "payment": payment,
                }
                if len(target_skus) > 1:
                    pending_payload["basket_skus"] = target_skus
                if quantity != 1:
                    pending_payload["quantity"] = quantity
                if len(verified_items) == 1:
                    pending_payload["price_vnd"] = verified_items[0][1]
                if address:
                    pending_payload["address"] = address
                if pending_order.get("checkout_confirmed"):
                    pending_payload["checkout_confirmed"] = True
                context.state.working_memory["pending_order"] = pending_payload

        # order.create is a deterministic, identity-bound mutation. Never
        # expose it to the LLM after the gate above, even when confirmation or
        # identity is incomplete: model-generated phone/customer IDs are not
        # accepted as a fallback.
        remaining.discard("create_new_order")

        update_confirmed = any(
            signal in text
            for signal in (
                "làm thủ tục đổi",
                "làm thủ tục",
                "thực hiện đổi",
                "đổi cho anh",
                "đổi cho chị",
                "tiến hành đổi",
            )
        )
        if "update_order" in remaining and update_confirmed:
            status_result = _orchestrated_result(
                verified_calls, "order.status"
            )
            order = _single_order(status_result)
            # Never fall back to a remembered ID after the current verified
            # lookup returned no unique order; that memory is stale/ambiguous.
            order_id = order.get("order_id") if order else None
            new_sku = _requested_exchange_sku(context)
            stock = _orchestrated_result(
                verified_calls, "inventory.check", sku=new_sku
            )
            if (
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
                await invoke("update_order", args)
                context.state.working_memory.pop("order_update_blocker", None)
            elif not isinstance(order_id, str) or not order_id:
                context.state.working_memory["order_update_blocker"] = (
                    "order_not_found"
                )
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
                f"{call_date}T00:00:00" if call_date else datetime.now().isoformat()
            )
            await invoke(
                "mcp_escalate_to_human",
                {
                    "reason": "medical_advice_out_of_scope",
                    "customer_id": (
                        context.identity.customer_id if context.identity else None
                    ),
                    "summary": "Khách yêu cầu tư vấn y tế ngoài phạm vi bán hàng.",
                    "customer_phone": _customer_phone(context),
                    "customer_name": profile.get("name"),
                    "escalation_reason": "medical_advice_out_of_scope",
                    "conversation_summary": _clip_text(
                        context.call_brief.summary if context.call_brief else "", 500
                    ),
                    "product_advised": facts.get("product_advised")
                    or facts.get("variant_sku"),
                    "price_quoted_vnd": facts.get("price_quoted_vnd"),
                    "open_questions": facts.get("medical_question")
                    or context.input.text,
                    "next_action": "Nhân viên có chuyên môn tiếp nhận và tư vấn an toàn.",
                    "generated_at": generated_at,
                },
            )
        remaining.discard("mcp_escalate_to_human")

        return calls, frozenset(remaining)


