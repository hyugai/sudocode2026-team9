import os
import sys
import json
import re
from datetime import datetime
from typing import Any, Optional

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.middleware.filesystem import FilesystemMiddleware
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)

from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from pathlib import Path

from telesale_agent.core.models import (
    TurnContext, TurnInput, ConversationState, TurnResult, 
    Message, Perception, ActionPlan, ActionResult, ActionStatus, Observation,
    AgentStep, PolicyDecision,
)
from telesale_agent.core.interfaces import ASREngine, CustomerMemoryRepository
from telesale_agent.application import CustomerContextService
from telesale_agent.adapters.llm.model_factory import (
    create_chat_model,
    model_provider_key,
    resolve_model_config,
)
from telesale_agent.adapters.llm.usage_tracking import (
    begin_usage_collection,
    finish_usage_collection,
    usage_stage,
)
from telesale_agent.core.tool_orchestration import (
    IntentToolRoutingMiddleware,
    TelesaleAgentRuntimeContext,
    is_explicit_callback_request,
    is_medical_handoff_request,
    select_tools_for_turn,
)


_BTC_TOOL_NAMES = {
    "retrieve_customer_profile": "crm.get_customer",
    "search_catalog": "catalog.search",
    "check_inventory": "inventory.check",
    "get_pricing_quote": "pricing.get_quote",
    "create_new_order": "order.create",
    "check_order_status": "order.status",
    "update_order": "order.update",
    "mcp_schedule_callback": "schedule.callback",
    "mcp_escalate_to_human": "handoff.transfer",
}

_DEFAULT_RECENT_MESSAGE_COUNT = 2
_DEFAULT_RECENT_MESSAGE_CHARS = 300
_DEFAULT_RECENT_CONTEXT_CHARS = 800


def _positive_int_env(name: str, default: int) -> int:
    """Read a positive integer limit without making startup fragile."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _clip_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _recent_conversation_context(messages: list[Message]) -> str:
    """Format a small application-owned history for a fresh agent turn."""
    count = _positive_int_env(
        "DEEPAGENT_RECENT_MESSAGE_COUNT", _DEFAULT_RECENT_MESSAGE_COUNT
    )
    per_message = _positive_int_env(
        "DEEPAGENT_RECENT_MESSAGE_CHARS", _DEFAULT_RECENT_MESSAGE_CHARS
    )
    total_limit = _positive_int_env(
        "DEEPAGENT_RECENT_CONTEXT_CHARS", _DEFAULT_RECENT_CONTEXT_CHARS
    )
    lines = [
        f"{message.role}: {_clip_text(message.content, per_message)}"
        for message in messages[-count:]
        if message.content
    ]
    return _clip_text("\n".join(lines), total_limit)


def _canonical_tool_name(name: str | None) -> str:
    if not name:
        return "unknown"
    return _BTC_TOOL_NAMES.get(name, name.replace("_", "."))


def _canonical_tool_args(name: str, args: Any) -> dict[str, Any]:
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


def _compact_orchestrated_result(name: str, result: Any) -> Any:
    """Project verified tool output to the fields needed for one reply.

    Full results remain in the trace and memory persister.  This projection is
    only for the LLM context, preventing large catalog/promotion payloads from
    being resent on every model request.
    """
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
        "callback_id",
        "callback_at",
        "moved_from",
        "ticket_id",
    )
    compact = {key: result[key] for key in keep if key in result}
    return compact or result


def _message_text(message: Any) -> str:
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


def _decode_tool_result(content: Any) -> Any:
    if isinstance(content, list):
        text_blocks = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and block.get("text")
        ]
        if len(text_blocks) == 1:
            return _decode_tool_result(text_blocks[0])
        if text_blocks:
            return [_decode_tool_result(block) for block in text_blocks]
        return content
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content


def _single_variant_sku(result: Any) -> str | None:
    """Return a SKU only when a catalog result resolves unambiguously."""
    if not isinstance(result, dict):
        return None
    items = [item for item in result.get("items", []) if isinstance(item, dict)]
    variants = [
        variant.get("variant_sku")
        for item in items
        for variant in (item.get("variants") or [])
        if isinstance(variant, dict) and variant.get("variant_sku")
    ]
    unique = list(dict.fromkeys(str(sku) for sku in variants))
    if len(unique) == 1:
        return unique[0]
    if not unique and len(items) == 1 and items[0].get("sku"):
        return str(items[0]["sku"])
    return None


def _known_variant_sku(context: TurnContext) -> str | None:
    """Resolve a previously verified SKU without asking the model to infer it."""
    if context.perception and isinstance(context.perception.entities, dict):
        for key in ("variant_sku", "sku"):
            value = context.perception.entities.get(key)
            if isinstance(value, str) and value:
                return value
    pending = context.state.working_memory.get("pending_order")
    if isinstance(pending, dict) and pending.get("sku"):
        return pending["sku"]
    if context.call_brief and isinstance(
        context.call_brief.remembered_preferences, dict
    ):
        facts = context.call_brief.remembered_preferences.get("facts") or {}
        if isinstance(facts, dict):
            for key in ("variant_sku", "product_advised"):
                value = facts.get(key)
                if isinstance(value, str) and value:
                    return value
    return None


def _known_fact(context: TurnContext, key: str) -> Any:
    if context.call_brief and isinstance(
        context.call_brief.remembered_preferences, dict
    ):
        facts = context.call_brief.remembered_preferences.get("facts") or {}
        if isinstance(facts, dict):
            return facts.get(key)
    return None


def _current_fact(context: TurnContext, *keys: str) -> Any:
    """Resolve a fact using current customer evidence before durable memory."""
    if context.perception:
        for source in (
            context.perception.memory_deltas,
            context.perception.entities,
        ):
            if not isinstance(source, dict):
                continue
            for key in keys:
                value = source.get(key)
                if value not in (None, "", []):
                    return value
    for key in keys:
        value = _known_fact(context, key)
        if value not in (None, "", []):
            return value
    return None


def _requested_order_id(context: TurnContext) -> str | None:
    explicit = _current_fact(context, "order_id")
    text = context.input.text or ""
    match = re.search(r"\b(?:OD|ORD)-?[A-Z0-9]+\b", text, re.IGNORECASE)
    if match:
        return match.group(0).upper()
    return explicit if isinstance(explicit, str) and explicit else None


def _payment_method(context: TurnContext) -> str | None:
    """Normalize the current choice before falling back to remembered payment."""
    text = (context.input.text or "").casefold()
    if "chuyển khoản" in text or re.search(r"\b(?:bank|transfer)\b", text):
        return "bank"
    if "cod" in text and not re.search(r"(?:không|khong)\s+cod", text):
        return "COD"
    value = _current_fact(context, "payment", "payment_method")
    if not isinstance(value, str) or not value.strip():
        return None
    folded = value.strip().casefold()
    if folded in {"bank_transfer", "bank", "chuyển khoản", "transfer"}:
        return "bank"
    return "COD" if folded == "cod" else value.strip()


def _current_turn_payment_method(context: TurnContext) -> str | None:
    """Return payment only when it is explicit in the current utterance/NLU."""
    text = (context.input.text or "").casefold()
    if "chuyển khoản" in text or re.search(r"\b(?:bank|transfer)\b", text):
        return "bank"
    if "cod" in text and not re.search(r"(?:không|khong)\s+cod", text):
        return "COD"
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    value = entities.get("payment") or entities.get("payment_method")
    if not isinstance(value, str) or not value.strip():
        return None
    folded = value.strip().casefold()
    if folded in {"bank_transfer", "bank", "chuyển khoản", "transfer"}:
        return "bank"
    return "COD" if folded == "cod" else value.strip()


def _current_turn_has_delivery_address(
    context: TurnContext,
    *,
    allow_bare_reply: bool = False,
) -> bool:
    """Tell current address evidence apart from an address loaded from memory."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    if any(
        isinstance(entities.get(key), str) and len(entities[key].strip()) >= 6
        for key in ("delivery_address", "shipping_address", "address")
    ):
        return True
    text = (context.input.text or "").strip()
    if re.search(
        r"(?:địa\s*chỉ(?:\s+(?:giao|nhận)\s+hàng)?\s*(?:là|:)?|"
        r"(?:giờ\s+)?giao(?:\s+(?:đến|về|qua|tới))?(?:\s+cho\s+(?:anh|chị|em|tôi))?)\s+"
        r"(?:số\s+)?\d+",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    return bool(allow_bare_reply and len(text) >= 8 and re.search(r"\d", text))


def _quantity(context: TurnContext) -> int:
    value = _current_fact(context, "quantity", "qty", "quantity_each")
    if isinstance(value, bool):
        return 1
    try:
        parsed = int(value)
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass
    text = (context.input.text or "").casefold()
    word_map = {"một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5}
    m = re.search(
        r"\b(\d+|một|hai|ba|bốn|năm)\s*(?:chiếc|cái|bộ|sản\s*phẩm|máy|đôi|hộp|bình|gói|cuộn|cây|áo|quần)\b",
        text,
    )
    if m:
        val = m.group(1)
        if val.isdigit():
            return int(val)
        if val in word_map:
            return word_map[val]
    return 1


def _basket_skus(context: TurnContext) -> list[str]:
    value = _current_fact(context, "basket_skus")
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            str(sku).strip()
            for sku in value
            if isinstance(sku, str) and sku.strip()
        )
    )


def _select_brief_facts(
    context: TurnContext,
    facts: dict[str, Any],
    limit: int = 6,
) -> list[tuple[str, Any]]:
    """Select a small intent-relevant projection of durable customer facts."""
    intents = set(context.perception.intents or []) if context.perception else set()
    if context.perception and context.perception.intent:
        intents.add(context.perception.intent)
    priorities: list[str] = []
    if intents.intersection({"create_order", "provide_info"}):
        priorities.extend(
            [
                "basket_skus",
                "variant_sku",
                "product_advised",
                "price_quoted_vnd",
                "delivery_address",
                "payment",
                "quantity",
                "quantity_each",
                "budget_vnd",
            ]
        )
    if "update_order" in intents:
        priorities.extend(
            [
                "order_id",
                "variant_sku",
                "pending_variant_sku",
                "pending_size",
                "delivery_address",
                "size",
                "color",
            ]
        )
    if intents.intersection({"ask_product", "price_objection"}):
        priorities.extend(
            [
                "product_advised",
                "variant_sku",
                "basket_skus",
                "budget_vnd",
                "room_area_m2",
                "has_children",
                "price_quoted_vnd",
            ]
        )
    if "end_call" in intents:
        priorities.extend(
            [
                "callback_at",
                "blocker",
                "product_advised",
                "price_quoted_vnd",
                "delivery_address",
                "payment",
            ]
        )
    if "complain" in intents:
        priorities.extend(
            ["order_id", "owned_sku", "variant_sku", "product_advised"]
        )
    priorities.extend(
        [
            "order_id",
            "basket_skus",
            "variant_sku",
            "product_advised",
            "delivery_address",
            "payment",
            "price_quoted_vnd",
            "callback_at",
            "blocker",
            "family_approved",
        ]
    )
    selected: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for key in priorities:
        value = facts.get(key)
        if key not in seen and value not in (None, "", []):
            selected.append((key, value))
            seen.add(key)
            if len(selected) >= limit:
                return selected
    for key, value in reversed(list(facts.items())):
        if key not in seen and value not in (None, "", []):
            selected.append((key, value))
            seen.add(key)
            if len(selected) >= limit:
                break
    return selected


def _customer_phone(context: TurnContext) -> str | None:
    """Return only the phone already verified by CRM/identity resolution."""
    profile = context.state.customer_profile or {}
    candidates = [
        profile.get("phone") if isinstance(profile, dict) else None,
        context.identity.phone if context.identity else None,
        context.input.customer_hint,
    ]
    return next(
        (value for value in candidates if isinstance(value, str) and value),
        None,
    )


def _normalize_callback_at(value: Any) -> str | None:
    """Normalize common callback timestamp shapes to an ISO minute string."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    candidates = [raw]
    # Gemini occasionally emits ``HH:MM YYYY-MM-DD`` for a Vietnamese phrase.
    reversed_match = re.fullmatch(
        r"(?P<time>\d{1,2}:\d{2})\s+(?P<date>\d{4}-\d{2}-\d{2})",
        raw,
    )
    if reversed_match:
        candidates.insert(
            0,
            f"{reversed_match.group('date')}T{reversed_match.group('time')}",
        )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace(" ", "T", 1))
        except ValueError:
            continue
        return parsed.isoformat(timespec="minutes")
    return None


def _requested_callback_at(context: TurnContext) -> str | None:
    """Resolve the requested callback time from explicit current-turn evidence."""
    text = context.input.text or ""
    date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    time_match = re.search(
        r"\b([01]?\d|2[0-3])(?:\s*:\s*([0-5]\d)|\s*giờ(?:\s*([0-5]?\d)\s*phút)?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if date_match and time_match:
        minute = time_match.group(2) or time_match.group(3) or "00"
        return f"{date_match.group(1)}T{int(time_match.group(1)):02d}:{int(minute):02d}"

    sources: list[Any] = []
    if context.perception:
        if isinstance(context.perception.memory_deltas, dict):
            sources.append(context.perception.memory_deltas.get("callback_at"))
        if isinstance(context.perception.entities, dict):
            sources.append(context.perception.entities.get("callback_at"))
    return next(
        (
            normalized
            for value in sources
            if (normalized := _normalize_callback_at(value)) is not None
        ),
        None,
    )


def _callback_adjustment_note(tool_calls: list[dict[str, Any]]) -> str | None:
    """Return an authoritative customer-facing note for a moved callback."""
    for call in reversed(tool_calls):
        if call.get("name") != "schedule.callback":
            continue
        result = call.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        moved_from = _normalize_callback_at(result.get("moved_from"))
        actual = _normalize_callback_at(result.get("callback_at"))
        if not moved_from or not actual or moved_from == actual:
            return None
        requested_dt = datetime.fromisoformat(moved_from)
        actual_dt = datetime.fromisoformat(actual)
        return (
            "Lưu ý: lịch gọi lại ban đầu vào "
            f"{requested_dt:%H:%M ngày %d/%m/%Y} rơi vào ngày nghỉ, "
            "nên hệ thống đã chuyển lịch sang "
            f"{actual_dt:%H:%M ngày %d/%m/%Y}."
        )
    return None


def _delivery_address(context: TurnContext) -> str | None:
    """Resolve an explicit current-turn or CRM-verified delivery address."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    profile = context.state.customer_profile or {}
    brief_profile = (
        context.call_brief.verified_customer_data
        if context.call_brief
        and isinstance(context.call_brief.verified_customer_data, dict)
        else {}
    )
    pending = context.state.working_memory.get("pending_order") or {}
    text = (context.input.text or "").strip()
    explicit_match = re.search(
        r"(?:địa\s*chỉ(?:\s+(?:giao|nhận)\s+hàng)?\s*(?:là|:)?|"
        r"(?:giờ\s+)?giao(?:\s+(?:đến|về|qua|tới))?(?:\s+cho\s+(?:anh|chị|em|tôi))?)\s+"
        r"(?P<address>(?:số\s+)?\d+[^!?\r\n]+?)"
        r"(?=\s*(?:,?\s*(?:thanh\s+toán|cod\b|chuyển\s+khoản|tiền\s+mặt|hôm\s+nay|nhé|nha)|[.!?]\s*$|[!?]|\.\s+(?!(?:hồ|chí|minh|hcm))\b|$))",
        text,
        flags=re.IGNORECASE,
    )
    explicit_address = (
        explicit_match.group("address").strip(" .,") if explicit_match else None
    )
    if (
        isinstance(pending, dict)
        and pending
        and len(text) >= 8
        and re.search(r"\d", text)
    ):
        # This is the direct answer to our preceding address question. Prefer
        # it over an occasionally truncated NLU entity (for example "1").
        cleaned = re.sub(
            r"^(?:địa\s*chỉ(?:\s+giao\s+hàng|\s+nhận\s+hàng)?\s*(?:là|:)?\s*)",
            "",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\s+(?:nhé|nha)(?:\s+em)?[.!]?$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        return cleaned or text
    candidates = [
        entities.get("delivery_address"),
        entities.get("shipping_address"),
        entities.get("address"),
        explicit_address,
        pending.get("address") if isinstance(pending, dict) else None,
        _known_fact(context, "delivery_address"),
        profile.get("address") if isinstance(profile, dict) else None,
        brief_profile.get("address"),
    ]
    address = next(
        (
            value.strip()
            for value in candidates
            if isinstance(value, str) and value.strip()
        ),
        None,
    )
    if address:
        return address

    # If the previous turn explicitly asked for the missing order address, a
    # street-like reply is the address even when the NLU omitted the entity.
    if (
        isinstance(pending, dict)
        and pending
        and len(text) >= 8
        and re.search(r"\d", text)
    ):
        return text
    return None


def _single_order(result: Any) -> dict[str, Any] | None:
    """Return one unambiguous order from a verified order.status result."""
    if not isinstance(result, dict):
        return None
    orders = result.get("orders") or []
    if len(orders) != 1 or not isinstance(orders[0], dict):
        return None
    return orders[0]


def _orchestrated_result(
    calls: list[dict[str, Any]],
    name: str,
    *,
    sku: str | None = None,
) -> Any:
    """Find a successful, already verified orchestration result."""
    for call in reversed(calls):
        if call.get("name") != name:
            continue
        args = call.get("args") or {}
        if sku and args.get("sku") != sku:
            continue
        result = call.get("result")
        if not (isinstance(result, dict) and result.get("error")):
            return result
    return None


def _latest_verified_sku(calls: list[dict[str, Any]]) -> str | None:
    """Prefer a SKU verified for the current turn over remembered products."""
    for preferred_name in ("pricing.get_quote", "inventory.check"):
        for call in reversed(calls):
            args = call.get("args") or {}
            result = call.get("result")
            if (
                call.get("name") == preferred_name
                and isinstance(args.get("sku"), str)
                and not (isinstance(result, dict) and result.get("error"))
            ):
                return args["sku"]
    for call in reversed(calls):
        if call.get("name") == "catalog.search":
            sku = _single_variant_sku(call.get("result"))
            if sku:
                return sku
    return None


def _format_vnd(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", ".") + " đồng"
    except (TypeError, ValueError):
        return ""


def _safe_fallback_response(
    context: TurnContext,
    tool_calls: list[dict[str, Any]],
) -> str:
    """Produce a grounded customer response when the model returns no text."""
    for call in reversed(tool_calls):
        result = call.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        name = call.get("name")
        if name == "order.create" and result.get("order_id"):
            return (
                f"Dạ em đã tạo đơn thành công, mã đơn là {result['order_id']}. "
                "Thông tin giao hàng đã được ghi nhận ạ."
            )
        if name == "order.update" and result.get("order_id"):
            return (
                f"Dạ em đã cập nhật đơn {result['order_id']} thành công theo "
                "yêu cầu của mình ạ."
            )
        if name == "schedule.callback" and result.get("callback_at"):
            return f"Dạ em đã ghi nhận lịch gọi lại vào {result['callback_at']} ạ."
        if name == "handoff.transfer" and result.get("ticket_id"):
            return (
                "Dạ nội dung này cần người phụ trách chuyên môn hỗ trợ. "
                "Em đã chuyển đầy đủ thông tin để mình không phải trình bày lại ạ."
            )
        if name == "pricing.get_quote" and result.get("final_price_vnd") is not None:
            price = _format_vnd(result["final_price_vnd"])
            return f"Dạ giá hiện tại đã được hệ thống xác nhận là {price} ạ."
        if name == "inventory.check" and result.get("in_stock") is not None:
            if result.get("in_stock"):
                return "Dạ sản phẩm hiện đang còn hàng ạ."
            restock = result.get("restock_expected")
            return (
                f"Dạ sản phẩm hiện tạm hết hàng, dự kiến nhập lại vào {restock} ạ."
                if restock
                else "Dạ sản phẩm hiện tạm hết hàng và chưa có lịch nhập lại ạ."
            )

    pending = context.state.working_memory.get("pending_order")
    if isinstance(pending, dict) and pending:
        missing = []
        if not _delivery_address(context):
            missing.append("địa chỉ giao hàng")
        if not _payment_method(context):
            missing.append("phương thức thanh toán")
        if missing:
            return "Dạ để hoàn tất đơn, mình cho em xin " + " và ".join(missing) + " ạ?"
    if context.state.working_memory.get("order_update_blocker") == "order_not_found":
        return (
            "Dạ em chưa tìm thấy đơn phù hợp từ thông tin đã xác minh. "
            "Mình cho em xin mã đơn khác để em kiểm tra tiếp ạ?"
        )
    return "Dạ em đã ghi nhận yêu cầu của mình. Em sẽ hỗ trợ theo thông tin đã xác minh ạ."


def _requested_exchange_sku(context: TurnContext) -> str | None:
    """Derive a new apparel variant only from a verified prior SKU + new size."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    explicit = entities.get("new_variant_sku")
    if isinstance(explicit, str) and explicit:
        return explicit
    requested_size = entities.get("requested_size")
    text = context.input.text or ""
    exchange_request = bool(
        re.search(
            r"(?:đổi|chuyển|lên|xuống)[^?.!]{0,30}\bsize\s*"
            r"(?:\d+|s|m|l|xl)\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    # Prefer the destination after "sang" over the first size in the phrase.
    # In "đổi từ size 38 sang 39", the first size is the owned/source size.
    target_match = re.search(
        r"\b(?:đổi|chuyển)\b[^?.!]{0,45}\bsang\s+(?:size\s*)?"
        r"(\d+|s|m|l|xl)\b",
        text,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:lên|xuống)\s+size\s*(\d+|s|m|l|xl)\b",
        text,
        flags=re.IGNORECASE,
    )
    if target_match:
        requested_size = target_match.group(1)
    elif requested_size is None and exchange_request:
        requested_size = entities.get("size")
    if requested_size is None:
        match = (
            re.search(
                r"\bsize\s*(\d+|s|m|l|xl)\b",
                text,
                flags=re.IGNORECASE,
            )
            if exchange_request
            else None
        )
        requested_size = match.group(1) if match else None
    if requested_size is None:
        pending = _known_fact(context, "pending_variant_sku")
        return pending if isinstance(pending, str) and pending else None
    current_sku = _known_variant_sku(context)
    if requested_size is None or not current_sku:
        return None
    match = re.fullmatch(
        r"(?P<product>SKU-[A-Z0-9-]+)-(?P<size>\d+|S|M|L|XL)-(?P<color>[A-Z]+)",
        current_sku,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return (
        f"{match.group('product')}-{str(requested_size).upper()}-"
        f"{match.group('color')}"
    ).upper()


def _catalog_query(context: TurnContext) -> str:
    """Build a compact catalog query while retaining requested variant data."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    product = next(
        (
            entities.get(key)
            for key in ("product_name", "product", "name", "query")
            if entities.get(key)
        ),
        None,
    )
    if not product:
        return context.input.text or ""
    parts = [str(product)]
    if entities.get("size") is not None:
        parts.append(f"size {entities['size']}")
    if entities.get("color"):
        parts.append(f"màu {entities['color']}")
    return " ".join(parts)


def _current_turn_messages(messages: list[Any]) -> list[Any]:
    """Return messages produced after the most recent user message."""
    start = 0
    for index, message in enumerate(messages):
        if getattr(message, "type", None) in {"human", "user"}:
            start = index + 1
    return messages[start:]


def extract_deepagent_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    """Pair DeepAgent AI tool calls with ToolMessage results for one turn."""
    pending: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []

    for message in _current_turn_messages(messages):
        tool_calls = getattr(message, "tool_calls", None) or []
        for raw_call in tool_calls:
            if not isinstance(raw_call, dict):
                continue
            call_id = str(raw_call.get("id") or f"tool-{len(ordered) + 1}")
            canonical_name = _canonical_tool_name(raw_call.get("name"))
            record = {
                "id": call_id,
                "name": canonical_name,
                "args": _canonical_tool_args(
                    canonical_name, raw_call.get("args") or {}
                ),
                "result": None,
            }
            pending[call_id] = record
            ordered.append(record)

        if getattr(message, "type", None) == "tool":
            call_id = str(getattr(message, "tool_call_id", "") or "")
            if call_id in pending:
                pending[call_id]["result"] = _decode_tool_result(
                    getattr(message, "content", "")
                )

    return ordered


def _tool_calls_to_steps(tool_calls: list[dict[str, Any]]) -> list[AgentStep]:
    steps = []
    for call in tool_calls:
        result = call.get("result")
        output = result if isinstance(result, dict) else {"value": result}
        error = output.get("error") if isinstance(output, dict) else None
        status = ActionStatus.FAILED if error else ActionStatus.EXECUTED
        plan = ActionPlan(
            action="tool_call",
            rationale="Tool selected by DeepAgent",
            tool_name=call["name"],
            arguments=call.get("args") or {},
        )
        policy = PolicyDecision(allowed=True, reason="Executed by DeepAgent")
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

class DeepAgentHarness:
    """A wrapper that uses deepagents to replace the custom pipeline loop."""
    
    def __init__(
        self, 
        asr: ASREngine = None,
        perceive=None,
        identity=None,
        crm=None,
        memory: CustomerMemoryRepository | None = None,
        retrieve=None,
        call_brief=None,
        guardrail=None,
        persist=None,
    ):
        self.asr = asr
        self.perceive = perceive
        self.identity = identity
        self.crm = crm
        self.memory = memory
        self.customer_context = (
            CustomerContextService(crm, memory) if crm and memory else None
        )
        self.retrieve = retrieve
        self.call_brief = call_brief
        self.guardrail = guardrail
        self.persist = persist
        self.checkpointer = MemorySaver()
        self.exit_stack = AsyncExitStack()
        self.agent = None
        self.mcp_tools: dict[str, Any] = {}

    async def __aenter__(self):
        if self.agent is not None:
            return self

        project_root = Path(__file__).resolve().parents[3]
        configured_agent_dir = os.environ.get("AGENT_INSTRUCTIONS_ROOT")
        agent_dir = (
            Path(configured_agent_dir)
            if configured_agent_dir
            else project_root / "data" / "memory-root" / "agents" / "telesales_agent"
        )
        missing_instructions = [
            name for name in ("soul.md", "agent.md", "tools.md")
            if not (agent_dir / name).is_file()
        ]
        if missing_instructions:
            raise FileNotFoundError(
                f"Missing DeepAgent instruction files in {agent_dir}: "
                + ", ".join(missing_instructions)
            )
        # Keep instructions as version-controlled .md files in memory-root,
        # but load them once at startup. MemoryMiddleware would append a large
        # generic self-edit guide on every model call even though customer
        # memory is owned by the configured application persister.
        instruction_prompt = "\n\n".join(
            (agent_dir / name).read_text(encoding="utf-8").strip()
            for name in ("soul.md", "agent.md", "tools.md")
        )
        minimal_filesystem = FilesystemMiddleware(
            tools=["read_file"],
            system_prompt="",
        )

        server_paths = [
            project_root / "src" / "mcp_servers" / "mcp_db.py",
            project_root / "src" / "mcp_servers" / "mcp_workflow.py",
        ]

        all_mcp_tools = []
        for srv_path in server_paths:
            if srv_path.exists():
                # Keep the parent's import path for subprocesses. This matters
                # for Windows evaluation runs where the venv launcher may fall
                # back to the base interpreter while packages remain in the
                # venv site-packages directory.
                params = StdioServerParameters(
                    command=sys.executable,
                    args=[str(srv_path)],
                    env=os.environ.copy(),
                )
                read, write = await self.exit_stack.enter_async_context(stdio_client(params))
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                tools = await load_mcp_tools(session)
                all_mcp_tools.extend(tools)
        self.mcp_tools = {
            tool.name: tool
            for tool in all_mcp_tools
            if isinstance(getattr(tool, "name", None), str)
        }
                
        model_config = resolve_model_config()
        model = create_chat_model(temperature=0.3)
        provider_key = model_provider_key(model, model_config.provider)

        # DeepAgent ships general filesystem/execution/subagent tools. This
        # telesales harness only needs the MCP business tools; hiding unused
        # schemas materially reduces every provider request while retaining the
        # DeepAgent runtime and middleware.
        register_harness_profile(
            provider_key,
            HarnessProfile(
                excluded_tools=frozenset(
                    {
                        "ls",
                        "read_file",
                        "write_file",
                        "edit_file",
                        "glob",
                        "grep",
                        "execute",
                    }
                ),
                general_purpose_subagent=GeneralPurposeSubagentProfile(
                    enabled=False
                ),
                excluded_middleware=frozenset(
                    {"SummarizationMiddleware", "PatchToolCallsMiddleware"}
                ),
            ),
        )

        self.agent = create_deep_agent(
            model=model,
            tools=all_mcp_tools,
            system_prompt=instruction_prompt,
            middleware=[
                IntentToolRoutingMiddleware(),
                ModelCallLimitMiddleware(
                    run_limit=_positive_int_env("DEEPAGENT_MAX_MODEL_CALLS", 3),
                    exit_behavior="end",
                ),
                ToolCallLimitMiddleware(
                    run_limit=_positive_int_env("DEEPAGENT_MAX_TOOL_CALLS", 3),
                    exit_behavior="end",
                ),
                minimal_filesystem,
            ],
            context_schema=TelesaleAgentRuntimeContext,
            checkpointer=self.checkpointer,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.exit_stack.aclose()
        self.agent = None

    def reset_customer_memory(self) -> None:
        """Reset an isolated evaluation memory repository between scenarios."""
        reset = getattr(self.memory, "reset", None)
        if callable(reset):
            reset()

    async def _prefetch_read_tools(
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

        basket_skus = _basket_skus(context)
        basket_order = bool(basket_skus and "create_new_order" in remaining)
        if basket_order:
            if "check_inventory" in remaining:
                for basket_sku in basket_skus:
                    inventory_args: dict[str, Any] = {"sku": basket_sku}
                    if call_date:
                        inventory_args["on"] = call_date
                    await invoke("check_inventory", inventory_args)
            if "get_pricing_quote" in remaining:
                for basket_sku in basket_skus:
                    pricing_args: dict[str, Any] = {
                        "sku": basket_sku,
                        "qty": _quantity(context),
                    }
                    if call_date:
                        pricing_args["on"] = call_date
                    if context.input.customer_hint:
                        pricing_args["customer_phone"] = context.input.customer_hint
                    if context.identity and context.identity.customer_id:
                        pricing_args["customer_id"] = context.identity.customer_id
                    await invoke("get_pricing_quote", pricing_args)

        # Catalog + inventory is a deterministic dependency chain when the
        # requested size/color resolves to exactly one variant. Running it here
        # replaces search->model->inventory->model with search->inventory->model.
        if {"search_catalog", "check_inventory"}.issubset(remaining):
            catalog_args: dict[str, Any] = {
                "query": _catalog_query(context),
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
            current_turn_sku = _single_variant_sku(catalog_result)
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
        if "get_pricing_quote" in remaining and basket_skus:
            for basket_sku in basket_skus:
                pricing_args = {"sku": basket_sku, "qty": _quantity(context)}
                if call_date:
                    pricing_args["on"] = call_date
                if context.input.customer_hint:
                    pricing_args["customer_phone"] = context.input.customer_hint
                if context.identity and context.identity.customer_id:
                    pricing_args["customer_id"] = context.identity.customer_id
                await invoke("get_pricing_quote", pricing_args)

        if "get_pricing_quote" in remaining:
            sku = current_turn_sku or _known_variant_sku(context)
            if sku:
                pricing_args = {"sku": sku, "qty": _quantity(context)}
                if call_date:
                    pricing_args["on"] = call_date
                if context.input.customer_hint:
                    pricing_args["customer_phone"] = context.input.customer_hint
                if context.identity and context.identity.customer_id:
                    pricing_args["customer_id"] = context.identity.customer_id
                await invoke("get_pricing_quote", pricing_args)

        return calls, frozenset(remaining)

    async def _execute_confirmed_mutation(
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

        pending_order = context.state.working_memory.get("pending_order")
        address = _delivery_address(context)
        create_negated = bool(
            re.search(
                r"\b(?:chưa|không|đừng)\b[^.!?]{0,24}"
                r"(?:lên\s+đơn|chốt(?:\s+đơn)?|đặt\s+mua|đặt\s+hàng|tạo\s+đơn|mua\s+ngay)",
                text,
                flags=re.IGNORECASE,
            )
        )
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
                    first_promo = promos[0] if promos else None
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

    async def run_turn(
        self,
        turn_input: TurnInput,
        state: ConversationState | None = None,
    ) -> TurnResult:
        """Run one turn and always close its provider-usage scope."""
        usage_token = begin_usage_collection()
        try:
            result = await self._run_turn_impl(turn_input, state)
        except BaseException:
            finish_usage_collection(usage_token)
            raise
        result.usage = finish_usage_collection(usage_token)
        return result

    async def _run_turn_impl(
        self,
        turn_input: TurnInput,
        state: ConversationState | None = None,
    ) -> TurnResult:
        """Execute the initialized Deep Agent pipeline for one turn."""
        if self.agent is None:
            raise RuntimeError(
                "DeepAgentHarness is not initialized; use "
                "build_deepagent_harness_async() or 'async with build_deepagent_harness()'."
            )

        state = state or ConversationState(conversation_id=turn_input.conversation_id)
        if state.conversation_id != turn_input.conversation_id:
            raise ValueError("state and input must belong to the same conversation")

        context = TurnContext(input=turn_input, state=state)
        # ConversationState is the canonical application history. Keep a copy
        # from before this turn so a fresh DeepAgent checkpoint can receive a
        # bounded amount of recent dialogue instead of its entire raw history.
        prior_messages = list(state.messages)
        if state.retrieved_data:
            context.retrieved = state.retrieved_data
        
        # 1. ASR
        if self.asr and context.input.audio and not context.input.text:
            transcript = await self.asr.transcribe(context)
            if transcript:
                context.input.text = transcript

        # 2. Pre-processing Nodes
        # 2a. Initialization phase (Only runs once per conversation)
        if not context.state.identity:
            if self.identity:
                context.identity = await self.identity.resolve_identity(context)
                context.state.identity = context.identity
            
            if self.customer_context:
                await self.customer_context.hydrate(context)
        else:
            context.identity = context.state.identity
            if self.customer_context and context.state.customer_memory is None:
                await self.customer_context.hydrate(context)
            
        # 2b. Turn-based phase (Runs every turn)
        if self.perceive:
            with usage_stage("perception"):
                context.perception = await self.perceive.perceive(context)
            context.state.messages.append(
                Message("customer", context.perception.transcript)
            )
            if context.perception and context.perception.memory_deltas:
                context.state.memory_deltas.update(context.perception.memory_deltas)

        if self.retrieve:
            from telesale_agent.config.intent_taxonomy import SKIP_RETRIEVAL_INTENTS
            # Skip retrieval if the intent is explicitly marked as not needing knowledge
            should_retrieve = True
            if context.perception:
                # If ALL intents detected are in SKIP_RETRIEVAL_INTENTS, skip the VectorDB search
                if context.perception.intents and all(i in SKIP_RETRIEVAL_INTENTS for i in context.perception.intents):
                    should_retrieve = False
                elif context.perception.intent in SKIP_RETRIEVAL_INTENTS and not context.perception.intents:
                    should_retrieve = False
                    
            if should_retrieve:
                context.retrieved = await self.retrieve.retrieve(context)
                context.state.retrieved_data = context.retrieved

        if self.customer_context:
            # The previous turn persists before returning. Reloading here makes
            # that canonical memory the input to this turn's new call brief.
            self.customer_context.refresh_memory(context)

        if self.call_brief:
            context.call_brief = await self.call_brief.build_call_brief(context)
            context.state.call_brief = context.call_brief

        # Inject compact, relevant context into the user message
        user_text = context.input.text or "[Audio]"
        notes = []
        if context.identity and context.identity.customer_id:
            notes.append(f"Customer ID: {context.identity.customer_id}")
        call_date = context.input.metadata.get("call_date")
        if call_date:
            notes.append(f"Current Call Date: {call_date}")

        recent_context = _recent_conversation_context(prior_messages)
        if recent_context:
            notes.append("Recent Conversation:\n" + recent_context)

        if context.perception:
            turn_delta = []
            if context.perception.intent and context.perception.intent != "unknown":
                turn_delta.append(f"intent={context.perception.intent}")
            if context.perception.entities:
                turn_delta.append(
                    "entities=" + _clip_text(context.perception.entities, 500)
                )
            if turn_delta:
                notes.append("Current Turn: " + " | ".join(turn_delta))

        # The brief is rebuilt from canonical memory each turn. Keep the
        # projection compact so its size is bounded as the call gets longer.
        if context.call_brief:
            cb = context.call_brief
            brief_parts = []
            if cb.customer_name:
                brief_parts.append(f"Name: {cb.customer_name}")
            addr = cb.verified_customer_data.get("address") if isinstance(cb.verified_customer_data, dict) else None
            if addr:
                brief_parts.append(f"Saved Address: {addr}")
            phone = cb.verified_customer_data.get("phone") if isinstance(cb.verified_customer_data, dict) else None
            if phone:
                brief_parts.append(f"Phone: {phone}")
            if cb.remembered_preferences and isinstance(cb.remembered_preferences, dict):
                facts = cb.remembered_preferences.get("facts") or {}
                if isinstance(facts, dict) and facts:
                    fact_items = [
                        f"{key}: {_clip_text(value, 120)}"
                        for key, value in _select_brief_facts(context, facts)
                    ]
                    if fact_items:
                        brief_parts.append(f"Known Facts: {', '.join(fact_items)}")
                else:
                    atomic = cb.remembered_preferences.get("atomic_facts") or []
                    if isinstance(atomic, list) and atomic:
                        legacy = [
                            _clip_text(f.get("content", ""), 180)
                            for f in atomic[-5:]
                            if isinstance(f, dict) and f.get("content")
                        ]
                        if legacy:
                            brief_parts.append(f"Known Facts: {', '.join(legacy)}")
            elif cb.summary:
                brief_parts.append(f"Past Summary: {_clip_text(cb.summary, 240)}")
            if brief_parts:
                notes.append("Customer Brief: " + " | ".join(brief_parts))

        # Only inject compact knowledge hints if turn 1 (state.turn_number == 0) to avoid bloat
        if state.turn_number == 0 and context.retrieved and context.retrieved.knowledge:
            items = []
            for item in context.retrieved.knowledge[:3]:
                if isinstance(item, dict):
                    if "sku" in item:
                        items.append(f"{item.get('sku')}: {item.get('name')} ({item.get('list_price_vnd')}đ)")
                    elif "policy_chunk" in item:
                        items.append(str(item["policy_chunk"])[:120])
                elif isinstance(item, str):
                    items.append(item[:120])
            if items:
                notes.append("Catalog/Policy Hints: " + " ; ".join(items))

        if notes:
            enriched_user_msg = f"{user_text}\n\n[System Context: {' // '.join(notes)}]"
        else:
            enriched_user_msg = user_text

        print("\n" + "="*50)
        print(f"STARTING DEEP AGENT RUN: {user_text}")
        print("="*50)

        # 3. Invoke Deep Agent. The default turn scope prevents the graph
        # checkpointer from replaying an ever-growing raw message/tool history.
        # The application-owned ConversationState supplies bounded continuity.
        checkpoint_scope = os.environ.get(
            "DEEPAGENT_CHECKPOINT_SCOPE", "turn"
        ).strip().lower()
        if checkpoint_scope == "conversation":
            thread_id = state.conversation_id
        else:
            thread_id = f"{state.conversation_id}__turn_{state.turn_number + 1}"
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": _positive_int_env("DEEPAGENT_RECURSION_LIMIT", 30),
        }
        memory_facts = {}
        if context.call_brief and isinstance(
            context.call_brief.remembered_preferences, dict
        ):
            candidate_facts = context.call_brief.remembered_preferences.get("facts")
            if isinstance(candidate_facts, dict):
                memory_facts = candidate_facts
        allowed_tools = select_tools_for_turn(
            context.perception,
            context.input.text,
            memory_facts,
        )
        if (
            context.state.working_memory.get("pending_order")
            and _delivery_address(context)
        ):
            allowed_tools = frozenset(
                set(allowed_tools)
                | {"create_new_order", "check_inventory", "get_pricing_quote"}
            )
        prefetched_calls, allowed_tools = await self._prefetch_read_tools(
            context,
            allowed_tools,
        )
        mutation_calls, allowed_tools = await self._execute_confirmed_mutation(
            context,
            allowed_tools,
            prefetched_calls,
        )
        orchestrated_calls = [*prefetched_calls, *mutation_calls]
        pending_order = context.state.working_memory.get("pending_order")
        if isinstance(pending_order, dict) and pending_order:
            missing_order_fields = []
            if not _delivery_address(context):
                missing_order_fields.append("delivery address")
            if not _payment_method(context):
                missing_order_fields.append("payment method")
            if missing_order_fields:
                enriched_user_msg += (
                    "\n\n[Required order information missing: "
                    + ", ".join(missing_order_fields)
                    + ". Ask only for these missing fields. Do not ask again "
                    "for known product, price, quantity, address, or payment "
                    "fields, and do not claim that an order was created.]"
                )
        if context.state.working_memory.get("order_update_blocker") == "order_not_found":
            enriched_user_msg += (
                "\n\n[Verified order lookup found no matching order. Do not "
                "claim that an exchange/update succeeded and do not call "
                "update_order. Ask for an alternative order identifier only "
                "if needed to continue.]"
            )
        exchange_target = _requested_exchange_sku(context)
        exchange_executed = any(
            call.get("name") == "order.update" for call in mutation_calls
        )
        if exchange_target and not exchange_executed:
            enriched_user_msg += (
                "\n\n[The requested exchange target is "
                f"{exchange_target}, but no order.update succeeded this turn. "
                "Do not claim it was updated in the system; only confirm the "
                "target/eligibility or ask for the remaining confirmation.]"
            )
        duplicate_orders = context.state.working_memory.get(
            "order_create_duplicate_prevented"
        )
        if isinstance(duplicate_orders, dict) and duplicate_orders:
            enriched_user_msg += (
                "\n\n[The requested item(s) were already created earlier in "
                "this same call. Do not create another order and do not claim "
                "a new order was created. Confirm the existing order ID(s): "
                + json.dumps(duplicate_orders, ensure_ascii=False)
                + ".]"
            )
        if orchestrated_calls:
            verified_reads = [
                {
                    "name": call["name"],
                    "args": call["args"],
                    "result": _compact_orchestrated_result(
                        call["name"], call["result"]
                    ),
                }
                for call in orchestrated_calls
            ]
            enriched_user_msg += (
                "\n\n[Verified orchestrated-tool results: "
                + _clip_text(
                    json.dumps(verified_reads, ensure_ascii=False),
                    _positive_int_env("DEEPAGENT_PREFETCH_CONTEXT_CHARS", 2_400),
                )
                + "]"
            )
            if _callback_adjustment_note(orchestrated_calls):
                enriched_user_msg += (
                    "\n\n[The callback tool moved the requested time. Tell the "
                    "customer the final callback_at from the verified result and "
                    "why it changed. Never confirm moved_from as the final schedule.]"
                )
        allowed_tool_text = ", ".join(sorted(allowed_tools)) or "none"
        enriched_user_msg += (
            "\n\n[Context precedence: explicit current customer statement > "
            "verified current tool result > current-scenario memory > CRM. "
            "Never ask for a non-conflicting field already shown in Customer "
            "Brief. Current price, stock, and promotion claims require a "
            "verified result for the current call date.]"
            f"\n\n[System Note - Tool Budget: The complete allowlist for this "
            f"turn is: {allowed_tool_text}. Never call a tool outside this "
            "allowlist even if general instructions mention it. Do not claim "
            "price, stock, order, or address facts without corresponding verified "
            "context/tool results. If the customer did not ask about price, do "
            "not call pricing and do not state a price. Do not repeat a tool call. "
            "After the necessary allowed tools succeed, answer immediately. Keep "
            "the final answer concise and always finish the last sentence.]"
        )

        print(
            f"   -> Context: scope={checkpoint_scope or 'turn'}, "
            f"prompt_chars={len(enriched_user_msg)}, "
            f"recent_messages={min(len(prior_messages), _positive_int_env('DEEPAGENT_RECENT_MESSAGE_COUNT', _DEFAULT_RECENT_MESSAGE_COUNT))}, "
            f"allowed_tools={sorted(allowed_tools)}"
        )
        
        with usage_stage("main_agent"):
            result = await self.agent.ainvoke(
                {"messages": [{"role": "user", "content": enriched_user_msg}]},
                config=config,
                context={"allowed_tools": sorted(allowed_tools)},
            )
        
        # Extract the current response and every tool call/result produced for
        # this turn. LangGraph returns the whole checkpoint message history.
        messages = result.get("messages", [])
        tool_calls = [
            *[call for call in orchestrated_calls if not call.get("_cached")],
            *extract_deepagent_tool_calls(messages),
        ]
        steps = _tool_calls_to_steps(tool_calls)
        context.steps = steps
        context.tool_results = {
            str(call.get("id")): call.get("result") for call in tool_calls
        }
        response_text = ""
        for message in reversed(_current_turn_messages(messages)):
            if getattr(message, "type", None) in {"ai", "assistant"}:
                response_text = _message_text(message)
                if response_text:
                    break

        if not response_text.strip():
            response_text = _safe_fallback_response(context, orchestrated_calls)

        callback_note = _callback_adjustment_note(tool_calls)
        if callback_note and callback_note not in response_text:
            response_text = f"{response_text.rstrip()}\n\n{callback_note}".strip()

        if self.guardrail and response_text:
            context.plan = ActionPlan(
                action="respond_to_customer",
                rationale="DeepAgent final response safety check",
                response_text=response_text,
            )
            context.policy = await self.guardrail.check(context)
            if context.policy.safe_plan is not None:
                response_text = context.policy.safe_plan.response_text or ""

        print(f"   -> Agent Response: {response_text}")
        print("\nDEEP AGENT RUN COMPLETED!")
        print("="*50 + "\n")
        
        # Save to state
        if response_text:
            state.messages.append(Message("agent", response_text))

        memory_writes = []
        if self.persist:
            with usage_stage("memory_persister"):
                memory_writes = await self.persist.persist(context) or []

        state.turn_number += 1
        
        return TurnResult(
            conversation_id=state.conversation_id,
            turn_number=state.turn_number,
            response_text=response_text,
            perception=context.perception,
            identity=context.identity,
            retrieved=context.retrieved,
            call_brief=context.call_brief,
            action_result=ActionResult(status=ActionStatus.EXECUTED, output={"message": "Handled by Deep Agent"}),
            observation=Observation(
                summary="Deep agent executed",
                events=[{"tool_calls": len(tool_calls)}],
            ),
            steps=steps,
            state=state,
            tool_calls=tool_calls,
            memory_writes=memory_writes,
        )
