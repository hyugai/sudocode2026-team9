import os
import json
import logging
from groq import AsyncGroq
from telesale_agent.core.interfaces import Persister
from telesale_agent.core.models import TurnContext
from telesale_agent.adapters.db.client import db_client

logger = logging.getLogger(__name__)

class LLMPersister(Persister):
    """Sử dụng LLM để tóm tắt các cuộc gọi kết thúc và lưu vào Supabase."""

    def __init__(self):
        self.client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = os.getenv("MODEL_NAME", "openai/gpt-oss-120b")

    async def persist(self, context: TurnContext) -> None:
        if os.environ.get("IS_EVAL") == "true":
            print("[PERSIST] Skipped during evaluation run.")
            return

        print(f"[PERSIST] Checking messages length: {len(context.state.messages)}")
        if len(context.state.messages) < 2:
            print("[PERSIST] Not enough messages, skipping persist.")
            return
        
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

        chat_history = []
        for msg in context.state.messages:
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
            
            if context.identity and context.identity.customer_id:
                # 1. Update M1 Profile (Short-term -> Long-term memory_deltas)
                if context.state.memory_deltas:
                    db_client.update_customer_attributes(
                        phone=context.identity.customer_id,
                        deltas=context.state.memory_deltas
                    )
                    print(f"[PERSIST] Updated Profile attributes for {context.identity.customer_id}: {context.state.memory_deltas}")

                # 2. Update M1 Episodic (Session summary)
                summary_str = f"Facts: {summary_dict.get('facts_established')} | Product: {summary_dict.get('product_advised')} | Blocker: {summary_dict.get('blocker')}"
                
                db_client.add_customer_session(
                    phone=context.identity.customer_id,
                    summary=summary_str,
                    outcome="pending"
                )
                print(f"[PERSIST] Saved session to Supabase for customer {context.identity.customer_id}")

        except Exception as e:
            print(f"[PERSIST] Error in LLMPersister: {e}")
