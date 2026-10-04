import os
import json
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq

from telesale_agent.core.interfaces import CallBriefBuilder
from telesale_agent.core.models import CallBrief, TurnContext
from telesale_agent.config.settings import settings

class NeedsSchema(BaseModel):
    needs: list[str] = Field(
        description="List of facts or needs established in previous sessions (e.g. 'Customer wants AirPure X', 'Price budget is 5,000,000 VND', 'Customer is asking family'). Empty list if no history."
    )
    summary: str = Field(
        description="A brief summary of the customer's history."
    )

class LLMCallBriefBuilder(CallBriefBuilder):
    """Uses LLM to summarize past sessions into a list of facts/needs."""

    def __init__(self, model_name: str = "openai/gpt-oss-120b"):
        api_key = settings.GROQ_API_KEY
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set in environment variables.")
        
        self.llm = ChatGroq(temperature=0, model_name=model_name, groq_api_key=api_key)
        self.structured_llm = self.llm.with_structured_output(NeedsSchema, method="json_mode")

    async def build_call_brief(self, context: TurnContext) -> CallBrief:
        if context.identity is None or context.retrieved is None:
            raise ValueError("identity and retrieved context are required")

        customer_name = context.identity.profile.get("name")
        past_sessions = context.state.past_history.get("sessions", []) if context.state.past_history else []
        
        if not past_sessions:
            return CallBrief(
                customer_id=context.identity.customer_id,
                customer_name=str(customer_name) if customer_name else None,
                summary="No previous customer history was found.",
                needs=[],
                active_promotions=context.retrieved.active_promotions,
            )

        # We have past sessions, use LLM to extract facts
        sessions_text = "\n".join([f"Session on {s.get('session_date')}: {s.get('summary')} (Outcome: {s.get('outcome')})" for s in past_sessions])
        
        prompt = f"""You are an assistant that extracts established facts and customer needs from past call logs.
Review the following past sessions for this customer:

{sessions_text}

Extract the key facts established (e.g., product interested in, price quoted, blocker, budget) into a list of short strings.
Respond ONLY with valid JSON matching this schema:
{{
  "needs": ["fact 1", "fact 2"],
  "summary": "Brief summary"
}}
"""
        
        try:
            result = await self.structured_llm.ainvoke(prompt)
            needs = result.needs
            summary = result.summary
        except Exception as e:
            print(f"LLMCallBriefBuilder Error: {e}")
            needs = []
            summary = "Error summarizing history."

        return CallBrief(
            customer_id=context.identity.customer_id,
            customer_name=str(customer_name) if customer_name else None,
            summary=summary,
            needs=needs,
            active_promotions=context.retrieved.active_promotions,
        )
