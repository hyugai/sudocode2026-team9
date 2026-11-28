"""Build bounded model context from application-owned turn state."""

from __future__ import annotations

import json
import os
from typing import Any

from telesale_agent.core.models import Message, TurnContext
from telesale_agent.application.customer_text import is_closing_turn
from telesale_agent.application.deepagent.understanding.policy_intent import deferred_policy_topic
from telesale_agent.application.deepagent.tools.protocol import compact_orchestrated_result
from telesale_agent.application.deepagent.context.order import (
    _delivery_address,
    _payment_method,
    _requested_exchange_sku,
)
from telesale_agent.application.deepagent.context.facts import _select_brief_facts


DEFAULT_RECENT_MESSAGE_COUNT = 2
DEFAULT_RECENT_MESSAGE_CHARS = 300
DEFAULT_RECENT_CONTEXT_CHARS = 800


def positive_int_env(name: str, default: int) -> int:
    """Read a positive integer limit without making startup fragile."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def clip_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def recent_conversation_context(messages: list[Message]) -> str:
    """Format a small application-owned history for a fresh agent turn."""
    count = positive_int_env(
        "DEEPAGENT_RECENT_MESSAGE_COUNT", DEFAULT_RECENT_MESSAGE_COUNT
    )
    per_message = positive_int_env(
        "DEEPAGENT_RECENT_MESSAGE_CHARS", DEFAULT_RECENT_MESSAGE_CHARS
    )
    total_limit = positive_int_env(
        "DEEPAGENT_RECENT_CONTEXT_CHARS", DEFAULT_RECENT_CONTEXT_CHARS
    )
    lines = [
        f"{message.role}: {clip_text(message.content, per_message)}"
        for message in messages[-count:]
        if message.content
    ]
    return clip_text("\n".join(lines), total_limit)


def build_base_user_message(
    context: TurnContext,
    prior_messages: list[Message],
) -> tuple[str, str]:
    """Project CRM, memory, recent dialogue and retrieval into one prompt."""
    user_text = (
        "[Closing turn: no further customer input]"
        if is_closing_turn(context)
        else (context.input.text or "[Audio]")
    )
    from telesale_agent.application.customer_addressing import addressing_instruction
    notes: list[str] = [addressing_instruction(context)]
    if context.identity and context.identity.customer_id:
        notes.append(f"Customer ID: {context.identity.customer_id}")
    call_date = context.input.metadata.get("call_date")
    if call_date:
        notes.append(f"Current Call Date: {call_date}")

    recent_context = recent_conversation_context(prior_messages)
    if recent_context:
        notes.append("Recent Conversation:\n" + recent_context)

    if context.perception:
        turn_delta = []
        if context.perception.intent and context.perception.intent != "unknown":
            turn_delta.append(f"intent={context.perception.intent}")
        if context.perception.entities:
            turn_delta.append(
                "entities=" + clip_text(context.perception.entities, 500)
            )
        if turn_delta:
            notes.append("Current Turn: " + " | ".join(turn_delta))

    if context.call_brief:
        brief = context.call_brief
        brief_parts = []
        if brief.customer_name:
            brief_parts.append(f"Name: {brief.customer_name}")
        verified = (
            brief.verified_customer_data
            if isinstance(brief.verified_customer_data, dict)
            else {}
        )
        if verified.get("address"):
            brief_parts.append(f"Saved Address: {verified['address']}")
        if verified.get("phone"):
            brief_parts.append(f"Phone: {verified['phone']}")
        if isinstance(brief.remembered_preferences, dict):
            facts = brief.remembered_preferences.get("facts") or {}
            if isinstance(facts, dict) and facts:
                fact_items = [
                    f"{key}: {clip_text(value, 240 if key == 'basket_product_names' else 120)}"
                    for key, value in _select_brief_facts(context, facts)
                ]
                if fact_items:
                    brief_parts.append(f"Known Facts: {', '.join(fact_items)}")
            else:
                atomic = brief.remembered_preferences.get("atomic_facts") or []
                if isinstance(atomic, list) and atomic:
                    legacy = [
                        clip_text(item.get("content", ""), 180)
                        for item in atomic[-5:]
                        if isinstance(item, dict) and item.get("content")
                    ]
                    if legacy:
                        brief_parts.append(f"Known Facts: {', '.join(legacy)}")
        elif brief.summary:
            brief_parts.append(f"Past Summary: {clip_text(brief.summary, 240)}")
        if brief.unresolved_issues:
            brief_parts.append(
                "Unresolved Question: "
                + clip_text(brief.unresolved_issues[0], 300)
            )
        if brief_parts:
            notes.append("Customer Brief: " + " | ".join(brief_parts))

    if (
        context.state.turn_number == 0
        and context.retrieved
        and context.retrieved.knowledge
    ):
        items = []
        for item in context.retrieved.knowledge[:3]:
            if isinstance(item, dict):
                if "sku" in item:
                    items.append(
                        f"{item.get('sku')}: {item.get('name')} "
                        f"({item.get('list_price_vnd')}đ)"
                    )
                elif "policy_chunk" in item:
                    items.append(str(item["policy_chunk"])[:120])
            elif isinstance(item, str):
                items.append(item[:120])
        if items:
            notes.append("Catalog/Policy Hints: " + " ; ".join(items))

    if not notes:
        return user_text, user_text
    return user_text, f"{user_text}\n\n[System Context: {' // '.join(notes)}]"


def append_orchestration_context(
    context: TurnContext,
    enriched_user_message: str,
    allowed_tools: frozenset[str],
    mutation_calls: list[dict[str, Any]],
    orchestrated_calls: list[dict[str, Any]],
) -> str:
    """Add verified tool evidence and mutation-safety instructions."""
    message = enriched_user_message
    remembered_facts = (
        context.call_brief.remembered_preferences.get("facts") or {}
        if context.call_brief
        and isinstance(context.call_brief.remembered_preferences, dict)
        else {}
    )
    if isinstance(remembered_facts, dict) and remembered_facts.get("basket_product_names"):
        message += (
            "\n\n[Basket product names in Customer Brief came from catalog.search. "
            "Use those exact names for their SKUs; never guess a product "
            "name from an SKU abbreviation. A multi-item or multi-unit cart total "
            "needs current-date get_order_quote (pricing.quote_order) with all "
            "lines; never call pricing.get_quote separately per item.]"
        )
    if deferred_policy_topic(context.input.text):
        message += (
            "\n\n[The customer plans to ask about policy on a later call. "
            "Acknowledge and remember the topic; do not explain or quote "
            "current policy in this turn unless it was retrieved now.]"
        )
    closing = is_closing_turn(context)
    pending_order = context.state.working_memory.get("pending_order")
    if isinstance(pending_order, dict) and pending_order:
        missing_order_fields = []
        if pending_order.get("needs_variant"):
            missing_order_fields.append("exact product variant")
        if pending_order.get("price_changed"):
            missing_order_fields.append(
                f"customer consent to the verified price of {pending_order['price_vnd']} VND"
            )
        if not _delivery_address(context):
            missing_order_fields.append("delivery address")
        if not _payment_method(context):
            missing_order_fields.append("payment method")
        if missing_order_fields:
            if closing:
                message += (
                    "\n\n[Closing turn: no order was created because required "
                    "information is still missing ("
                    + ", ".join(missing_order_fields)
                    + "). Briefly note that the order has not been placed yet "
                    "and close politely without asking new or repeated questions "
                    "and without claiming an order ID.]"
                )
            else:
                message += (
                    "\n\n[Required order information missing: "
                    + ", ".join(missing_order_fields)
                    + ". Ask only for these missing fields. Do not ask again "
                    "for known product, price, quantity, address, or payment "
                    "fields, and do not claim that an order was created.]"
                )
    if closing:
        created_this_turn = any(
            call.get("name") == "order.create"
            and isinstance(call.get("result"), dict)
            and call["result"].get("order_id")
            and not call["result"].get("error")
            for call in mutation_calls
        )
        last_order = context.state.working_memory.get("last_created_order")
        if created_this_turn:
            message += (
                "\n\n[Closing turn: order.create succeeded above. Concisely read "
                "back the confirmed order (products, verified prices/total, "
                "delivery address, payment method, order ID, estimated delivery "
                "if present) and close the call politely. Do not ask any new questions.]"
            )
        elif isinstance(last_order, dict) and last_order.get("order_id"):
            message += (
                "\n\n[Closing turn: an order was already created earlier in this "
                "call: "
                + json.dumps(last_order, ensure_ascii=False)
                + ". Concisely read back the confirmed order details and close "
                "the call politely. Do not create another order and do not ask "
                "any new questions.]"
            )
        else:
            message += (
                "\n\n[Closing turn: the customer has finished speaking. Give a "
                "brief, polite wrap-up summarizing only verified outcomes from "
                "this call. Do not invent prices, stock, or order IDs, and do "
                "not ask any new or repeated questions.]"
            )

    exchange_blocker = context.state.working_memory.get("order_update_blocker")
    if exchange_blocker == "order_not_found":
        message += (
            "\n\n[Verified order lookup found no matching order. Do not "
            "claim that an exchange/update succeeded and do not call "
            "update_order. Ask for an alternative order identifier only "
            "if needed to continue.]"
        )
    elif exchange_blocker == "variant_missing":
        message += "\n\n[The order is verified. Ask which size the customer wants to exchange to.]"
    elif exchange_blocker in {"variant_unverified", "update_failed"}:
        message += "\n\n[The exchange was not completed. Report the verified result and avoid a confirmation.]"

    exchange_target = _requested_exchange_sku(context)
    exchange_executed = any(
        call.get("name") == "order.update" for call in mutation_calls
    )
    if exchange_target and not exchange_executed:
        message += (
            "\n\n[The requested exchange target is "
            f"{exchange_target}, but no order.update succeeded this turn. "
            "Do not claim it was updated in the system; only confirm the "
            "target/eligibility or ask for the remaining confirmation.]"
        )

    duplicate_orders = context.state.working_memory.get(
        "order_create_duplicate_prevented"
    )
    if isinstance(duplicate_orders, dict) and duplicate_orders:
        message += (
            "\n\n[The requested item(s) were already created earlier in "
            "this same call. Do not create another order and do not claim "
            "a new order was created. Confirm the existing order ID(s): "
            + json.dumps(duplicate_orders, ensure_ascii=False)
            + ".]"
        )

    if orchestrated_calls:
        verified_results = [
            {
                "name": call["name"],
                "args": call["args"],
                "result": compact_orchestrated_result(
                    call["name"], call["result"]
                ),
            }
            for call in orchestrated_calls
        ]
        message += (
            "\n\n[Verified orchestrated-tool results: "
            + clip_text(
                json.dumps(verified_results, ensure_ascii=False),
                positive_int_env("DEEPAGENT_PREFETCH_CONTEXT_CHARS", 2_400),
            )
            + "]"
        )
    if context.state.working_memory.get("callback_reply"):
        message += (
            "\n\n[The application will supply the callback confirmation or "
            "the question for missing scheduling fields. Answer any other "
            "customer requests without repeating or changing the callback details.]"
        )

    allowed_tool_text = ", ".join(sorted(allowed_tools)) or "none"
    message += (
        "\n\n[Context precedence: current customer statements override "
        "memory for customer-owned facts (choice, address, consent), but "
        "never override verified business facts (policy, price, promotion, "
        "stock). For business facts use the current verified tool result. "
        "Otherwise prefer current-scenario memory over CRM. "
        "Never ask for a non-conflicting field already shown in Customer "
        "Brief. Current price, stock, and promotion claims require a "
        "verified result for the current call date.]"
        f"\n\n[System Note - Tool Budget: The complete allowlist for this "
        f"turn is: {allowed_tool_text}. Never call a tool outside this "
        "allowlist even if general instructions mention it. Do not claim "
        "price, stock, order, or address facts without corresponding verified "
        "context/tool results. Do not claim a callback was booked unless the verified "
        "schedule.callback result has a callback ID and an effective time. "
        "If the customer did not ask about price, do "
        "not call pricing and do not state a price. Do not repeat a tool call. "
        "After the necessary allowed tools succeed, answer immediately. Keep "
        "the final answer concise and always finish the last sentence.]"
    )
    return message

