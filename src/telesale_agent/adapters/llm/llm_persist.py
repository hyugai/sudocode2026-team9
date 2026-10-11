import os
import json
import logging
from groq import AsyncGroq
from telesale_agent.core.interfaces import Persister
from telesale_agent.core.models import TurnContext
from telesale_agent.core.interfaces import CustomerMemoryRepository
from telesale_agent.adapters.memory.turn_persist import persist_turn_memory

logger = logging.getLogger(__name__)

class LLMPersister(Persister):
    """Summarize a turn and persist durable memory through the memory port."""

    def __init__(self, memory: CustomerMemoryRepository):
        self.client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = (
            os.getenv("GROQ_MODEL")
            or os.getenv("MODEL_NAME")
            or "openai/gpt-oss-20b"
        )
        self.memory = memory

    async def persist(self, context: TurnContext) -> list[dict]:
        if os.environ.get("IS_EVAL") == "true":
            print("[PERSIST] Skipped during evaluation run.")
            return []

        writes = persist_turn_memory(self.memory, context)

        print(f"[PERSIST] Checking messages length: {len(context.state.messages)}")
        if len(context.state.messages) < 2:
            print("[PERSIST] Not enough messages, skipping persist.")
            return writes

        customer_id = (
            context.identity.customer_id
            if context.identity and context.identity.customer_id
            else None
        )
        system_prompt = """
        Bạn là trợ lý tổng hợp thông tin cuộc gọi bán hàng.
        Dựa vào lịch sử chat, hãy tóm tắt ngắn gọn các thông tin sau (nếu có):
        - Nhu cầu khách hàng (diện tích, sở thích...)
        - Sản phẩm đang quan tâm
        - Rào cản/Lý do chưa chốt đơn (nếu có)
        
        Hãy trả về kết quả định dạng JSON với cấu trúc:
        {
            "facts_established": "Các sự kiện đã xác nhận",
            "product_advised": "Sản phẩm được tư vấn",
            "blocker": "Lý do chưa chốt"
        }
        Nếu không có thông tin, hãy để chuỗi rỗng "".
        Chỉ trả về JSON hợp lệ, không có markdown.
        """

        # Persist an episode for this turn, not a growing summary of the full call.
        chat_history = []
        for msg in context.state.messages[-2:]:
            role = "USER" if msg.role == "customer" else "AGENT"
            chat_history.append(f"{role}: {msg.content}")
        
        history_text = "\n".join(chat_history)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Lịch sử cuộc gọi:\n{history_text}"}
                ],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            
            raw_content = response.choices[0].message.content
            summary_dict = json.loads(raw_content)
            
            print(f"[PERSIST] LLMPersister generated summary: {summary_dict}")
            
            if customer_id:
                # Persist an episodic summary as .md.
                summary_str = f"Facts: {summary_dict.get('facts_established')} | Product: {summary_dict.get('product_advised')} | Blocker: {summary_dict.get('blocker')}"
                self.memory.record_episode(customer_id, summary_str)
                context.state.customer_memory = self.memory.load(customer_id)
                print(f"[PERSIST] Saved .md episode for customer {customer_id}")

        except Exception as e:
            print(f"[PERSIST] Error in LLMPersister: {e}")

        return writes
