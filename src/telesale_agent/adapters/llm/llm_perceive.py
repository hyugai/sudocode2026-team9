import re
from typing import Any
from pydantic import BaseModel, Field

from telesale_agent.core.interfaces import Perceiver
from telesale_agent.core.models import Perception, TurnContext
from telesale_agent.application.deepagent.understanding.policy_intent import deferred_policy_topic
from telesale_agent.application.deepagent.understanding.unverified_question import unit_specific_question
from telesale_agent.config.intent_taxonomy import INTENT_NAMES, build_intent_prompt_section
from telesale_agent.adapters.rules.pii_utils import mask_pii
from telesale_agent.adapters.llm.model_factory import create_chat_model

class IntentSchema(BaseModel):
    intents: list[str] = Field(
        description=f"List of intents. Choose one or more from: {', '.join(INTENT_NAMES)}"
    )
    entities: Any = Field(
        description="Entities extracted from the utterance. Must be a flat dictionary (e.g., {'product_name': 'headphones', 'price': 500000}), NOT a list.", 
        default_factory=dict
    )
    memory_deltas: Any = Field(
        description=(
            "Durable customer facts explicitly stated in this utterance. Use "
            "canonical keys such as room_area_m2, has_children, budget_vnd, "
            "blocker, family_approved, size, color, quantity, payment, or "
            "callback_at. Never infer product_advised, price_quoted_vnd, "
            "promo_code, order_id, address, phone, or agent suggestions."
        ),
        default_factory=dict
    )
    unit_specific_question_detected: bool = Field(
        default=False,
        description=(
            "True only when the customer asks for an unverified detail of one "
            "physical item, such as its serial, production batch/shift, "
            "inspection record, or warehouse measurement. False for generic "
            "product specifications and questions about previous conversations."
        ),
    )
    unit_specific_question_text: str = Field(
        default="",
        description=(
            "If detected, copy the exact customer question verbatim. Never "
            "paraphrase it or invent an answer; otherwise use an empty string."
        ),
    )


_MEMORY_KEY_ALIASES = {
    "room_size": "room_area_m2",
    "room_area": "room_area_m2",
    "budget": "budget_vnd",
    "has_kids": "has_children",
    "has_children": "has_children",
    "payment_method": "payment",
    "shipping_address": "delivery_address",
    "address": "delivery_address",
    "product": "product_advised",
    "sku": "product_advised",
    "price": "price_quoted_vnd",
    "price_vnd": "price_quoted_vnd",
}
_AUTHORITATIVE_ONLY_MEMORY_KEYS = {
    "product_advised",
    "variant_sku",
    "price_quoted_vnd",
    "promo_code",
    "order_id",
    "basket_skus",
    "removed_sku",
}
_SENSITIVE_OR_TRANSACTIONAL_KEYS = {
    "address",
    "delivery_address",
    "shipping_address",
    "phone",
    "customer_phone",
    "customer_id",
    "bank_account",
    "cccd",
    "cmnd",
}


def _number(value: Any) -> int | float | Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return value
    compact = re.sub(r"(?<=\d)[.,\s](?=\d{3}\b)", "", value.strip())
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:m[²2])?", compact, re.I)
    if not match:
        return value
    numeric = match.group(1).replace(",", ".")
    parsed = float(numeric)
    return int(parsed) if parsed.is_integer() else parsed


def canonicalize_memory_deltas(
    deltas: dict[str, Any],
    transcript: str,
    *,
    unit_specific_by_model: bool = False,
    unit_question_excerpt: str | None = None,
) -> dict[str, Any]:
    """Normalize NLU output and reject facts that require tool authority."""
    normalized: dict[str, Any] = {}
    transcript_folded = transcript.casefold()
    for raw_key, raw_value in deltas.items():
        if not isinstance(raw_key, str):
            continue
        key = re.sub(r"[^a-z0-9_]+", "_", raw_key.strip().casefold()).strip("_")
        key = _MEMORY_KEY_ALIASES.get(key, key)
        if (
            not key
            or key in _AUTHORITATIVE_ONLY_MEMORY_KEYS
            or key == "unresolved_question"
            or key.startswith("basket_item_")
            or key in _SENSITIVE_OR_TRANSACTIONAL_KEYS
        ):
            continue
        if key == "budget_vnd" and not re.search(
            r"ngân\s*sách|ngan\s*sach|tầm\s+\d|tam\s+\d|đổ\s*lại",
            transcript_folded,
            re.I,
        ):
            continue
        value = raw_value
        if key in {"budget_vnd", "room_area_m2", "size", "quantity"}:
            value = _number(value)
        elif key in {"family_approved", "has_children"}:
            if isinstance(value, str):
                folded = value.strip().casefold()
                if folded in {
                    "true", "yes", "y", "1", "có", "đồng ý", "đã đồng ý"
                }:
                    value = True
                elif folded in {
                    "false", "no", "n", "0", "không", "chưa đồng ý"
                }:
                    value = False
        normalized[key] = value

    # Deterministic guards fill the two high-value cross-call facts when the
    # structured model omits them. Both require literal customer evidence.
    if re.search(
        r"(?:cần|phải|còn\s+phải|để)\s+hỏi\s+(?:người\s+nhà|chồng|vợ)",
        transcript_folded,
        re.IGNORECASE,
    ):
        normalized.setdefault("blocker", "cần hỏi người nhà")
    if re.search(
        r"(?:người\s+nhà|chồng|vợ)\s+(?:đã\s+)?đồng\s+ý",
        transcript_folded,
        re.IGNORECASE,
    ):
        normalized["family_approved"] = True
    if re.search(
        r"(?:thuốc\s+kê\s+đơn|liều\s+thuốc|chẩn\s+đoán|điều\s+trị|"
        r"vấn\s+đề\s+sức\s+khỏe|câu\s+hỏi\s+y\s+tế)",
        transcript_folded,
        re.IGNORECASE,
    ):
        normalized["medical_question"] = transcript.strip()
    pending_policy_topic = deferred_policy_topic(transcript)
    if pending_policy_topic:
        normalized["blocker"] = f"chưa rõ {pending_policy_topic}"
    question = unit_specific_question(
        transcript,
        model_detected=unit_specific_by_model,
        model_excerpt=unit_question_excerpt,
    )
    if question:
        # Preserve the customer's wording, never an LLM paraphrase or answer.
        normalized["unresolved_question"] = mask_pii(question)[0]
    return normalized

class LLMPerceiver(Perceiver):
    """Use the configured LLM to extract intents and entities."""
    
    def __init__(self, model_name: str | None = None):
        self.llm = create_chat_model(temperature=0, model_name=model_name)
        self.structured_llm = self.llm.with_structured_output(IntentSchema)

    async def perceive(self, context: TurnContext) -> Perception:
        if context.input.text is None:
            raise ValueError("LLMPerceiver only processes text. ASR (e.g., Whisper) is required to convert audio to text first.")

        transcript = context.input.text.strip()
        
        # Mask PII in the raw transcript BEFORE sending to external LLM API
        # This ensures CCCD/STK/phone numbers never leave the system boundary.
        sanitised_transcript, _ = mask_pii(transcript)
        
        prompt = f"""You are an advanced NLU system for a Vietnamese telesales call center.
Your task: extract ALL intents and entities from the customer utterance below.

{build_intent_prompt_section()}
## IMPORTANT RULES
1. A single utterance CAN have multiple intents — return ALL that apply.
2. If the utterance mentions both a product AND a fee/policy keyword → return BOTH intents.
3. Extract entities as key-value pairs (product_name, brand, quantity).
4. Extract `memory_deltas` only for durable facts explicitly stated by the customer.
5. Use canonical memory keys: room_area_m2, has_children, budget_vnd, blocker,
   family_approved, size, color, quantity, payment, callback_at.
6. Never put product, quoted price, promotion, order ID, address, phone, or an
   agent recommendation in memory_deltas; those require verified tools/storage.
7. Detect questions about one physical item's unknown serial, batch, production
   shift, inspection record, or warehouse measurement. Set
   unit_specific_question_detected=true and copy the exact question into
   unit_specific_question_text. Do not flag generic model specifications or
   "do you remember my earlier question?" as a new item-specific question.

Respond ONLY with a valid JSON object. Do not include markdown formatting or extra text.

Customer utterance: "{sanitised_transcript}"
"""
        
        # Call the configured provider for structured output.
        try:
            result = await self.structured_llm.ainvoke(prompt)
            
            
            parsed_entities = result.entities
            if isinstance(parsed_entities, list):
                if len(parsed_entities) > 0 and isinstance(parsed_entities[0], dict):
                    parsed_entities = parsed_entities[0]
                else:
                    parsed_entities = {}
            parsed_deltas = result.memory_deltas
            if not isinstance(parsed_deltas, dict):
                parsed_deltas = {}
            parsed_deltas = canonicalize_memory_deltas(
                parsed_deltas,
                transcript,
                unit_specific_by_model=bool(
                    getattr(result, "unit_specific_question_detected", False)
                ),
                unit_question_excerpt=getattr(
                    result, "unit_specific_question_text", ""
                ),
            )

            return Perception(
                transcript=transcript,
                intent=result.intents[0] if result.intents else "unknown",
                intents=result.intents,
                entities=parsed_entities,
                memory_deltas=parsed_deltas,
                confidence=1.0
            )
        except Exception as e:
            # Fallback if LLM fails
            print(f"LLMPerceiver Error: {e}")
            return Perception(
                transcript=transcript,
                intent="unknown",
                entities={},
                memory_deltas=canonicalize_memory_deltas({}, transcript),
                confidence=0.0
            )
