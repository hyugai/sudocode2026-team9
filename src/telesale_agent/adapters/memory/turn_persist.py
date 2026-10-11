from __future__ import annotations

from typing import Any

from telesale_agent.core.interfaces import CustomerMemoryRepository, Persister
from telesale_agent.core.models import TurnContext


def _tool_memory_candidates(context: TurnContext) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    for step in context.steps:
        name = step.plan.tool_name
        args = step.plan.arguments or {}
        output = step.action_result.output or {}
        if name == "pricing.get_quote":
            if args.get("sku"):
                candidates["product_advised"] = args["sku"]
            if output.get("final_price_vnd") is not None:
                candidates["price_quoted_vnd"] = output["final_price_vnd"]
            promos = output.get("applied_promos") or []
            if promos:
                candidates["promo_code"] = promos[0] if len(promos) == 1 else promos
        elif name == "order.create":
            if args.get("sku"):
                candidates["product_advised"] = args["sku"]
            if args.get("price_vnd") is not None:
                candidates["price_quoted_vnd"] = args["price_vnd"]
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

