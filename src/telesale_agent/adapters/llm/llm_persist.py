from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from telesale_agent.adapters.llm.model_factory import create_chat_model
from telesale_agent.adapters.memory.turn_persist import persist_turn_memory
from telesale_agent.core.interfaces import CustomerMemoryRepository, Persister
from telesale_agent.core.models import TurnContext


logger = logging.getLogger(__name__)


class EpisodeSummarySchema(BaseModel):
    facts_established: str = Field(
        default="",
        description="Confirmed customer facts learned in this turn only.",
    )
    product_advised: str = Field(
        default="",
        description="Product or variant discussed in this turn.",
    )
    blocker: str = Field(
        default="",
        description="Confirmed reason the customer has not completed the purchase.",
    )
    foresights: list[str] = Field(
        default_factory=list,
        description=(
            "Zero to three concrete recommendations for a future call, supported "
            "by this turn. Return an empty list instead of generic advice."
        ),
    )


class LLMPersister(Persister):
    """Persist canonical facts plus learned episodic memory after each turn."""

    def __init__(self, memory: CustomerMemoryRepository):
        self.llm = create_chat_model(temperature=0)
        self.structured_llm = self.llm.with_structured_output(EpisodeSummarySchema)
        self.memory = memory

    @staticmethod
    def _source_id(context: TurnContext) -> str:
        call_key = context.input.metadata.get("call_key", "call")
        return f"{call_key}#turn{context.state.turn_number + 1}"

    async def persist(self, context: TurnContext) -> list[dict]:
        # Bootstrap selects either isolated in-memory storage or durable files.
        writes = persist_turn_memory(self.memory, context)

        customer_id = (
            context.identity.customer_id
            if context.identity and context.identity.customer_id
            else None
        )
        if not customer_id:
            return writes

        # Atomic facts are an append-only audit trail. facts.md remains the
        # latest-value snapshot and is updated by persist_turn_memory above.
        for write in writes:
            value = json.dumps(write["value"], ensure_ascii=False)
            self.memory.record_atomic_fact(
                customer_id,
                f"{write['key']}: {value} | source: {write['source']}",
            )

        if len(context.state.messages) < 2:
            context.state.customer_memory = self.memory.load(customer_id)
            return writes

        system_prompt = """You summarize one Vietnamese telesales turn for long-term memory.
Use only information explicitly present in the two messages. Do not infer private
attributes, intent, preferences, or future actions without evidence. Return the
requested structured fields. Keep every field concise. Foresights must be concrete
next-call recommendations supported by the conversation; otherwise return none."""

        chat_history = []
        for message in context.state.messages[-2:]:
            role = "CUSTOMER" if message.role == "customer" else "AGENT"
            chat_history.append(f"{role}: {message.content}")

        try:
            summary = await self.structured_llm.ainvoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n".join(chat_history)},
                ]
            )

            episode_parts = []
            if summary.facts_established:
                episode_parts.append(f"Facts: {summary.facts_established}")
            if summary.product_advised:
                episode_parts.append(f"Product: {summary.product_advised}")
            if summary.blocker:
                episode_parts.append(f"Blocker: {summary.blocker}")

            if episode_parts:
                self.memory.record_episode(
                    customer_id,
                    " | ".join(episode_parts),
                    source_id=self._source_id(context),
                )

            for foresight in summary.foresights[:3]:
                if foresight.strip():
                    self.memory.record_foresight(customer_id, foresight.strip())

            context.state.customer_memory = self.memory.load(customer_id)
        except Exception as exc:
            # Reliable facts remain saved even if LLM summarization fails.
            logger.warning("LLM memory summarization failed: %s", exc)

        return writes
