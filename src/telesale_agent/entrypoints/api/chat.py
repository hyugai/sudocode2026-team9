from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import os

# Add src to Python path so we can import the agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from telesale_agent.bootstrap import build_deepagent_harness_async
from telesale_agent.core.models import TurnInput, ConversationState
from contextlib import asynccontextmanager

# Global harness reference
harness = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global harness
    print("🚀 Khởi tạo kết nối MCP Servers cho API Backend...")
    harness = await build_deepagent_harness_async()
    yield
    print("🛑 Đóng kết nối MCP Servers...")
    if harness:
        await harness.__aexit__(None, None, None)

app = FastAPI(title="Telesale Agent API", lifespan=lifespan)

# Allow CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory session store for the UI
sessions = {}

class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    customer_phone: str | None = None

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    if req.conversation_id not in sessions:
        sessions[req.conversation_id] = ConversationState(conversation_id=req.conversation_id)
    
    state = sessions[req.conversation_id]
    turn_input = TurnInput(conversation_id=req.conversation_id, 
                          text=req.message,
                          customer_hint=req.customer_phone,
                          )
    
    result = await harness.run_turn(turn_input, state)
    
    debug_info = {
        "intent": result.perception.intent if result.perception else "unknown",
        "retrieved_knowledge": result.retrieved.knowledge if result.retrieved else [],
        "crm_profile": result.state.customer_profile,
        "customer_memory": result.state.customer_memory,
        "past_history": result.state.past_history,
        "steps": [
            {
                "action": step.plan.action,
                "rationale": step.plan.rationale,
                "tool": step.plan.tool_name,
                "tool_args": step.plan.arguments,
            }
            for step in result.steps
        ] if result.steps else []
    }
    
    return {
        "response": result.response_text,
        "debug": debug_info
    }

# Optional root endpoint for health checks
@app.get("/")
def read_root():
    return {"status": "ok"}
