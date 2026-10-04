import os
from typing import Any
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq

from telesale_agent.core.interfaces import Perceiver
from telesale_agent.core.models import Perception, TurnContext
from telesale_agent.config.settings import settings
from telesale_agent.config.intent_taxonomy import INTENT_NAMES, build_intent_prompt_section
from telesale_agent.adapters.rules.pii_utils import mask_pii

class IntentSchema(BaseModel):
    intents: list[str] = Field(
        description=f"List of intents. Choose one or more from: {', '.join(INTENT_NAMES)}"
    )
    entities: Any = Field(
        description="Entities extracted from the utterance. Must be a flat dictionary (e.g., {'product_name': 'headphones', 'price': 500000}), NOT a list.", 
        default_factory=dict
    )
    memory_deltas: dict = Field(
        description="Profile facts established in this utterance to be saved into long-term memory (e.g. {'room_size': '25m2', 'has_kids': True, 'budget': 5000000}). Return empty dict if no new facts.",
        default_factory=dict
    )

class LLMPerceiver(Perceiver):
    """Uses Groq LLM (LLaMA) to extract intents and entities from customer utterances."""
    
    def __init__(self, model_name: str = "openai/gpt-oss-20b"):
        api_key = settings.GROQ_API_KEY
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set in environment variables. Please check your .env file.")
        
        # Temperature = 0 for accurate, non-creative extraction
        self.llm = ChatGroq(temperature=0, model_name=model_name, groq_api_key=api_key)
        self.structured_llm = self.llm.with_structured_output(IntentSchema, method="json_mode")

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
4. Extract `memory_deltas` for any long-term profile facts the customer reveals (e.g., room_size, budget, has_kids).

Respond ONLY with a valid JSON object. Do not include markdown formatting or extra text.

Customer utterance: "{sanitised_transcript}"
"""
        
        # Call Groq API for structured JSON
        try:
            result = await self.structured_llm.ainvoke(prompt)
            
            
            parsed_entities = result.entities
            if isinstance(parsed_entities, list):
                if len(parsed_entities) > 0 and isinstance(parsed_entities[0], dict):
                    parsed_entities = parsed_entities[0]
                else:
                    parsed_entities = {}
            if not isinstance(parsed_entities, dict):
                parsed_entities = {}
                
            return Perception(
                transcript=transcript,
                intent=result.intents[0] if result.intents else "unknown",
                intents=result.intents,
                entities=parsed_entities,
                memory_deltas=result.memory_deltas,
                confidence=1.0
            )
        except Exception as e:
            # Fallback if LLM fails
            print(f"LLMPerceiver Error: {e}")
            return Perception(
                transcript=transcript,
                intent="unknown",
                entities={},
                confidence=0.0
            )
