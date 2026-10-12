from __future__ import annotations

from typing import Any
import re

from telesale_agent.core.interfaces import CustomerMemoryRepository, Persister
from telesale_agent.core.models import TurnContext


_APPAREL_VARIANT = re.compile(
    r"^(?P<product>SKU-[A-Z0-9-]+)-(?P<size>\d+|S|M|L|XL)-(?P<color>[A-Z]+)$",
    re.IGNORECASE,
)


def _variant_facts(sku: Any) -> dict[str, Any]:
    if not isinstance(sku, str) or not sku:
        return {}
    match = _APPAREL_VARIANT.fullmatch(sku)
    if not match:
        return {"product_advised": sku}
    size_value = match.group("size")
    return {
        "product_advised": match.group("product").upper(),
        "variant_sku": sku.upper(),
        "size": int(size_value) if size_value.isdigit() else size_value.upper(),
        "color": match.group("color").lower(),
    }


def _tool_memory_candidates(context: TurnContext) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    for step in context.steps:
        name = step.plan.tool_name
        args = step.plan.arguments or {}
        output = step.action_result.output or {}
        if name == "catalog.search":
            variant_skus = [
                variant.get("variant_sku")
                for item in output.get("items", [])
                if isinstance(item, dict)
                for variant in (item.get("variants") or [])
                if isinstance(variant, dict) and variant.get("variant_sku")
            ]
            if len(set(variant_skus)) == 1:
                candidates.update(_variant_facts(variant_skus[0]))
        elif name == "inventory.check":
            if args.get("sku"):
                candidates.update(_variant_facts(args["sku"]))
        elif name == "pricing.get_quote":
            if args.get("sku"):
                candidates.update(_variant_facts(args["sku"]))
            if output.get("final_price_vnd") is not None:
                candidates["price_quoted_vnd"] = output["final_price_vnd"]
            promos = output.get("applied_promos") or []
            if promos:
                candidates["promo_code"] = promos[0] if len(promos) == 1 else promos
        elif name == "order.create":
            if args.get("sku"):
                candidates.update(_variant_facts(args["sku"]))
            if args.get("price_vnd") is not None:
                candidates["price_quoted_vnd"] = args["price_vnd"]
            if args.get("payment"):
                candidates["payment"] = args["payment"]
            if output.get("order_id"):
                candidates["order_id"] = output["order_id"]
        elif name == "order.update":
            if args.get("new_variant_sku"):
                candidates.update(_variant_facts(args["new_variant_sku"]))
            if args.get("action"):
                candidates["last_order_action"] = args["action"]
    return candidates


def persist_turn_memory(
    memory: CustomerMemoryRepository,
    context: TurnContext,
) -> list[dict[str, Any]]:
    customer_id = (
        context.identity.customer_id
        if context.identity and context.identity.customer_id
        else None
    )
    if not customer_id:
        context.state.memory_deltas.clear()
        return []

    candidates = dict(context.state.memory_deltas)
    candidates.update(_tool_memory_candidates(context))
    source = (
        f"{context.input.metadata.get('call_key', 'call')}"
        f"#turn{context.state.turn_number + 1}"
    )
    writes = []
    for key, value in candidates.items():
        previous = memory.latest_fact(customer_id, key)
        operation = "supersede" if previous is not None and previous != value else "set"
        memory.upsert_fact(customer_id, key, value)
        writes.append(
            {
                "key": key,
                "value": value,
                "op": operation,
                "source": source,
                "customer_id": customer_id,
            }
        )

    context.state.memory_deltas.clear()
    context.state.customer_memory = memory.load(customer_id)
    return writes


class TurnMemoryPersister(Persister):
    """Persist structured turn facts without making another LLM request."""

    def __init__(self, memory: CustomerMemoryRepository):
        self.memory = memory

    async def persist(self, context: TurnContext) -> list[dict[str, Any]]:
        return persist_turn_memory(self.memory, context)

