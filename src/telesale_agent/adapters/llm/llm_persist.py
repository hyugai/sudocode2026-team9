from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from telesale_agent.adapters.llm.model_factory import create_chat_model
from telesale_agent.application.memory.persist import persist_turn_memory
from telesale_agent.core.interfaces import CustomerMemoryRepository, Persister
from telesale_agent.core.models import TurnContext
from telesale_agent.adapters.rules.pii_utils import mask_pii


logger = logging.getLogger(__name__)

_EMPTY_SUMMARY_VALUES = {
    "none",
    "null",
    "n/a",
    "không có",
    "không rõ",
    "không đề cập",
    "không đề cập cụ thể",
    "chưa có",
}


def _clean_summary_value(value: str) -> str:
    cleaned = " ".join((value or "").split()).strip(" |.;")
    return "" if cleaned.casefold() in _EMPTY_SUMMARY_VALUES else cleaned


def _normalized_memory_text(value: str) -> str:
    return " ".join(
        re.sub(r"[^\w\s]", " ", value.casefold(), flags=re.UNICODE).split()
    )


def _is_duplicate_foresight(candidate: str, existing: list[str]) -> bool:
    normalized = _normalized_memory_text(candidate)
    if not normalized:
        return True
    for value in existing:
        other = _normalized_memory_text(value.removeprefix("- "))
        if normalized == other:
            return True
        if other and SequenceMatcher(None, normalized, other).ratio() >= 0.82:
            return True
    return False


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
        scenario_id = context.input.metadata.get("scenario_id")
        call_key = context.input.metadata.get("call_key", "call")
        turn_id = f"{call_key}#turn{context.state.turn_number + 1}"
        return f"{scenario_id}:{turn_id}" if scenario_id else turn_id

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

        customer_text = (context.input.text or "").strip()
        if not customer_text:
            context.state.customer_memory = self.memory.load(customer_id)
            return writes

        system_prompt = """You summarize one Vietnamese telesales turn for long-term memory.
Use only information explicitly present in CUSTOMER MESSAGE or VERIFIED FACT UPDATES.
Do not infer private attributes, intent, preferences, products, or future actions
without evidence. Return the requested structured fields. An agent statement is not
customer evidence and is intentionally absent from this prompt. Never include phone
numbers, delivery addresses, identity numbers, bank details, or payment secrets.
Keep every field concise. Foresights must be concrete next-call recommendations
supported by the customer message and must not repeat EXISTING FORESIGHTS;
for an unanswered per-unit question, retain the question without inventing
where a serial/batch number will appear or promising a warehouse process;
otherwise return an empty list."""

        safe_customer_text, _ = mask_pii(customer_text)
        memory_snapshot = self.memory.load(customer_id)
        existing_foresights = [
            str(item.get("content", ""))
            for item in memory_snapshot.get("foresights", [])
            if isinstance(item, dict) and item.get("content")
        ]
        verified_updates = {
            write["key"]: write["value"]
            for write in writes
            if write.get("key") not in {"address", "delivery_address", "phone"}
        }
        learning_input = (
            f"CUSTOMER MESSAGE: {safe_customer_text}\n"
            "VERIFIED FACT UPDATES: "
            f"{json.dumps(verified_updates, ensure_ascii=False)}\n"
            "EXISTING FORESIGHTS: "
            f"{json.dumps(existing_foresights[-8:], ensure_ascii=False)}"
        )

        try:
            summary = await self.structured_llm.ainvoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": learning_input},
                ]
            )

            episode_parts = []
            facts_established = _clean_summary_value(summary.facts_established)
            product_advised = _clean_summary_value(summary.product_advised)
            blocker = _clean_summary_value(summary.blocker)
            if facts_established:
                episode_parts.append(f"Facts: {facts_established}")
            # A product may be retained only when named by the customer or
            # grounded by a deterministic/tool-backed fact write this turn.
            product_grounded = (
                product_advised.casefold() in customer_text.casefold()
                or any(
                    write.get("key") in {"product_advised", "variant_sku"}
                    for write in writes
                )
            )
            if product_advised and product_grounded:
                episode_parts.append(f"Product: {product_advised}")
            if blocker:
                episode_parts.append(f"Blocker: {blocker}")

            if episode_parts:
                self.memory.record_episode(
                    customer_id,
                    " | ".join(episode_parts),
                    source_id=self._source_id(context),
                )

            for foresight in summary.foresights[:3]:
                cleaned = _clean_summary_value(foresight)
                if cleaned and not _is_duplicate_foresight(
                    cleaned, existing_foresights
                ):
                    self.memory.record_foresight(customer_id, cleaned)
                    existing_foresights.append(cleaned)

            context.state.customer_memory = self.memory.load(customer_id)
        except Exception as exc:
            # Reliable facts remain saved even if LLM summarization fails.
            logger.warning("LLM memory summarization failed: %s", exc)

        return writes
