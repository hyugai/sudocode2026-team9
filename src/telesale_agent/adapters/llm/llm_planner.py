import os
import json
import dataclasses
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq

from telesale_agent.core.interfaces import Planner
from telesale_agent.core.models import ActionPlan, TurnContext
from telesale_agent.config.settings import settings

class ActionPlanSchema(BaseModel):
    action: str = Field(description="The next action to take: 'respond_to_customer', 'transfer_to_human', or 'call_api'")
    rationale: str = Field(description="The rationale behind this decision")
    target_intent: str | None = Field(description="The target intent if applicable", default=None)
    response_text: str = Field(description="The final response text to speak/chat with the customer (must be in Vietnamese). DO NOT leave empty. If calling a tool, explain you are doing it.", default="Dạ vâng, anh chị chờ em chút ạ.")
    tool_name: str | None = Field(description="The name of the tool to call if action is 'call_api'", default=None)
    arguments: dict | None = Field(description="Arguments for the tool as a JSON object", default=None)

# Define tools the LLM can use
AVAILABLE_TOOLS = [
    {
        "name": "order.create",
        "description": "Create a new order for the customer.",
        "parameters": {

            "customer_phone": "String, customer's phone number",
            "sku": "String, the product SKU code to order (e.g., 'SKU-AP-Y')",
            "qty": "Integer, quantity to order",
            "price_vnd": "Integer, the agreed price in VND (e.g., 5200000)",
            "payment": "String, payment method (e.g., 'COD')",
            "address": "String, delivery address"
        }
    },
    {
        "name": "inventory.check",
        "description": "Check inventory for a product.",
        "parameters": {
            "sku": "String, the product SKU code"
        }
    },
    {
        "name": "pricing.get_quote",
        "description": "Get the final price and active promotions for a product.",
        "parameters": {
            "sku": "String, the product SKU code",
            "qty": "Integer, quantity (default 1)"
        }
    },
    {
        "name": "schedule.callback",
        "description": "Schedule a callback for a customer who needs time to think.",
        "parameters": {
            "customer_phone": "String, customer's phone number",
            "callback_at": "String, callback time (e.g., '2026-10-17T10:00')"
        }
    }
]

class LLMPlanner(Planner):
    """
    Planner using Groq LLM (LLaMA) to decide the next action and generate a response.
    """
    
    def __init__(self, model_name: str = "openai/gpt-oss-120b"):
        api_key = settings.GROQ_API_KEY
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set in environment variables.")
        
        self.llm = ChatGroq(temperature=0.3, model_name=model_name, groq_api_key=api_key)
        self.structured_llm = self.llm.with_structured_output(ActionPlanSchema)
        
    def _format_steps(self, steps) -> str:
        if not steps:
            return "No previous actions in this turn."
        formatted = []
        for i, step in enumerate(steps, 1):
            tool = step.plan.tool_name or step.plan.action
            output = step.action_result.output if step.action_result else "No output"
            formatted.append(f"Step {i}: Called '{tool}' with args {step.plan.arguments}. Result: {json.dumps(output, ensure_ascii=False)}")
        return "\n".join(formatted)

    async def plan(self, context: TurnContext) -> ActionPlan:
        intent = context.perception.intent if context.perception else "unknown"
        transcript = context.perception.transcript if context.perception else ""
        
        call_brief = dataclasses.asdict(context.call_brief) if context.call_brief else {}
        knowledge = context.retrieved.knowledge if context.retrieved else []
        
        customer_profile = context.state.customer_profile or {}
        past_history = context.state.past_history or {}
        memory_deltas = context.state.memory_deltas or {}
        
        prompt = f"""You are a professional and skillful Telesales Agent.
Your task is to determine the next action and write a response for the customer based on the Call Brief, CRM Profile, and retrieved Knowledge.
NOTE: Your internal reasoning can be in English, but the final `response_text` MUST be in fluent, polite Vietnamese suitable for a phone conversation.

-- CUSTOMER INFO & CONTEXT --
Current Customer Intent: {intent}
Recent Customer Utterance: "{transcript}"
Call Brief:
{json.dumps(call_brief, ensure_ascii=False, indent=2)}

-- CUSTOMER CRM PROFILE (M1 Profile) --
{json.dumps(customer_profile, ensure_ascii=False, indent=2)}

-- CURRENT SESSION NEW FACTS (M1 Working Profile) --
{json.dumps(memory_deltas, ensure_ascii=False, indent=2)}

-- CUSTOMER PAST HISTORY (M1 Episodic) --
{json.dumps(past_history, ensure_ascii=False, indent=2)}

-- RETRIEVED KNOWLEDGE (RAG) --
{json.dumps(knowledge, ensure_ascii=False, indent=2)}

-- RECENT AGENT ACTIONS IN THIS TURN --
{self._format_steps(context.steps)}

-- AVAILABLE TOOLS --
You can use the following tools if the customer requests an action (like placing an order or checking stock):
{json.dumps(AVAILABLE_TOOLS, ensure_ascii=False, indent=2)}

-- INSTRUCTIONS --
1. Analyze the context and decide the next action:
   - 'respond_to_customer': If you just need to talk or answer a question.
   - 'call_api': If you need to trigger a system action (like creating an order). You MUST provide `tool_name` and `arguments`.
   - 'transfer_to_human': If the request is beyond your capability.
9. ALWAYS provide a `response_text` naturally and politely in Vietnamese, even if you are calling an API (e.g., "Dạ vâng, em đang lên đơn cho chị...").
3. USE the CRM Profile (like customer's name, honorific, past orders) to personalize your greeting.
4. Base your pricing and policy answers STRICTLY on the RETRIEVED KNOWLEDGE. Do not hallucinate information.
5. IMPORTANT ORDERING RULE: If the customer agrees to buy, you MUST collect their delivery address and payment method BEFORE calling `order.create`. If they haven't provided them, ask for them (action='respond_to_customer'). Once you have SKU, price, address, and payment method, use action='call_api' and tool_name='order.create'.
6. If the customer wants to think about it and asks you to call back later, use tool_name='schedule.callback'.

Formulate your action plan:"""

        try:
            result = await self.structured_llm.ainvoke(prompt)
            return ActionPlan(
                action=result.action,
                rationale=result.rationale,
                target_intent=result.target_intent,
                response_text=result.response_text,
                tool_name=result.tool_name,
                arguments=result.arguments or {}
            )
        except Exception as e:
            print(f"LLMPlanner Error: {e}")
            return ActionPlan(
                action="transfer_to_human",
                rationale=f"LLM Error: {str(e)}",
                response_text="Dạ em xin lỗi, hệ thống đang gặp chút sự cố. Em sẽ chuyển máy cho bạn tư vấn viên hỗ trợ mình ngay ạ."
            )
