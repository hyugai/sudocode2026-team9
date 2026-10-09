"""Gradio Chat UI for testing Telesale Agent with state tracking."""

import sys
import os
import gradio as gr
import json
import dataclasses

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from telesale_agent.bootstrap import build_default_harness, build_deepagent_harness_async
from telesale_agent.core.models import TurnInput, ConversationState

# Khởi tạo Global Instances
harness = None
state = ConversationState(conversation_id="gradio_test_session")

def format_json(obj) -> str:
    """Helper để convert Dataclass sang JSON string đẹp mắt."""
    if obj is None:
        return "{}"
    if dataclasses.is_dataclass(obj):
        return json.dumps(dataclasses.asdict(obj), indent=2, ensure_ascii=False)
    if hasattr(obj, '__dict__'):
        return json.dumps(obj.__dict__, indent=2, ensure_ascii=False)
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)

async def chat_interaction(user_message, history):
    """Hàm xử lý khi user gửi tin nhắn."""
    global state, harness
    
    if harness is None:
        print("Khởi tạo kết nối MCP Servers lần đầu (Chỉ chạy 1 lần)...")
        harness = await build_deepagent_harness_async()
        
    # 1. Tạo input
    input_data = TurnInput(
        conversation_id=state.conversation_id,
        text=user_message,
        channel="chat"
    )
    
    # 2. Chạy qua Graph
    result = await harness.run_turn(input_data, state)
    
    # 3. Lấy kết quả
    bot_message = result.response_text or "No response from agent."
    
    # 4. Trích xuất thông tin cho các Node Tracker
    perceive_text = f"```json\n{format_json(result.perception)}\n```"
    identity_text = f"```json\n{format_json(result.identity)}\n```"
    retrieve_text = f"```json\n{format_json(result.retrieved)}\n```"
    brief_text = f"```json\n{format_json(result.call_brief)}\n```"
    
    # 5. Lấy danh sách Agent Loop Steps
    steps_md = ""
    for idx, step in enumerate(result.steps, 1):
        steps_md += f"### Vòng {idx}\n"
        steps_md += f"- **Plan (Kế hoạch):** `{step.plan.action}` - {step.plan.rationale}\n"
        steps_md += f"- **Guardrail (Kiểm duyệt):** {'✅ Hợp lệ' if step.policy.allowed else '❌ Bị chặn'} ({step.policy.reason or 'Không có lý do'})\n"
        steps_md += f"- **Action Status:** `{step.action_result.status}`\n"
        steps_md += f"- **Observation (Quan sát):** {step.observation.summary}\n\n"
        steps_md += "---\n"
        
    if not steps_md:
        steps_md = "_Không có vòng lặp Agent nào được kích hoạt._"

    # 6. Cập nhật lịch sử chat UI
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": bot_message})
    
    return history, "", perceive_text, identity_text, retrieve_text, brief_text, steps_md

def clear_chat():
    """Reset lại State và xóa trắng UI."""
    global state
    state = ConversationState(conversation_id="gradio_test_session")
    return [], "", "{}", "{}", "{}", "{}", "_Chờ dữ liệu..._"

# ======= GIAO DIỆN UI GRADIO =======
with gr.Blocks(title="Telesale Agent Debugger", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🤖 Telesale Agent - Bảng Điều Khiển (LangGraph)")
    
    with gr.Row():
        # CỘT TRÁI: Giao diện Chat
        with gr.Column(scale=4):
            chatbot = gr.Chatbot(label="Cuộc trò chuyện", height=600)
            msg = gr.Textbox(label="Khách hàng nhắn:", placeholder="Nhập tin nhắn vào đây và ấn Enter hoặc Gửi...", lines=2)
            with gr.Row():
                send_btn = gr.Button("📩 Gửi tin nhắn", variant="primary")
                clear = gr.Button("🔄 Xóa hội thoại & Reset State")
            
        # CỘT PHẢI: Tracking từng Node
        with gr.Column(scale=5):
            gr.Markdown("## 🔍 Theo dõi Dữ liệu (State Tracker)")
            
            with gr.Accordion("1. Node Perceive (Nhận thức Input)", open=False):
                perceive_out = gr.Markdown("{}")
            
            with gr.Accordion("2. Node Identity (Định danh Khách hàng)", open=False):
                identity_out = gr.Markdown("{}")
                
            with gr.Accordion("3. Node Retrieve (Truy xuất CRM/Knowledge)", open=False):
                retrieve_out = gr.Markdown("{}")
                
            with gr.Accordion("4. Node Call Brief (Tổng hợp Ngữ cảnh)", open=False):
                brief_out = gr.Markdown("{}")
                
            with gr.Accordion("5->8. Agent Loop (Vòng lặp Hành động)", open=True):
                steps_out = gr.Markdown("_Chờ dữ liệu..._")

    # Bắt sự kiện
    msg.submit(
        chat_interaction,
        inputs=[msg, chatbot],
        outputs=[chatbot, msg, perceive_out, identity_out, retrieve_out, brief_out, steps_out]
    )
    
    send_btn.click(
        chat_interaction,
        inputs=[msg, chatbot],
        outputs=[chatbot, msg, perceive_out, identity_out, retrieve_out, brief_out, steps_out]
    )
    
    clear.click(
        clear_chat,
        outputs=[chatbot, msg, perceive_out, identity_out, retrieve_out, brief_out, steps_out]
    )

if __name__ == "__main__":
    demo.launch(server_port=7860)
