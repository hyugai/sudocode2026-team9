import asyncio
import os
import secrets
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
import sys

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

cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active call state is intentionally in-memory. Render is configured with one
# instance because customer .md memory lives on a persistent disk.
sessions: dict[str, ConversationState] = {}
session_locks: dict[str, asyncio.Lock] = {}


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    configured = os.environ.get("API_KEY", "").strip()
    if configured and (
        x_api_key is None or not secrets.compare_digest(x_api_key, configured)
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    customer_phone: str | None = None

@app.post("/api/chat", dependencies=[Depends(require_api_key)])
async def chat_endpoint(req: ChatRequest):
    if harness is None:
        raise HTTPException(status_code=503, detail="Agent is not ready")

    if req.conversation_id not in sessions:
        sessions[req.conversation_id] = ConversationState(conversation_id=req.conversation_id)
    lock = session_locks.setdefault(req.conversation_id, asyncio.Lock())

    async with lock:
        state = sessions[req.conversation_id]
        turn_input = TurnInput(
            conversation_id=req.conversation_id,
            text=req.message,
            customer_hint=req.customer_phone,
        )
        result = await harness.run_turn(turn_input, state)
        sessions[req.conversation_id] = result.state

    response = {"response": result.response_text}
    if os.environ.get("ENABLE_DEBUG_RESPONSE", "false").lower() == "true":
        response["debug"] = {
            "intent": result.perception.intent if result.perception else "unknown",
            "retrieved_knowledge": (
                result.retrieved.knowledge if result.retrieved else []
            ),
            "crm_profile": result.state.customer_profile,
            "customer_memory": result.state.customer_memory,
            "past_history": result.state.past_history,
            "tool_calls": result.tool_calls,
            "memory_writes": result.memory_writes,
            "usage": result.usage,
        }
    return response


@app.delete(
    "/api/sessions/{conversation_id}",
    dependencies=[Depends(require_api_key)],
)
async def clear_session(conversation_id: str):
    sessions.pop(conversation_id, None)
    session_locks.pop(conversation_id, None)
    return {"status": "cleared", "conversation_id": conversation_id}

# Optional root endpoint for health checks
@app.get("/")
def read_root():
    return {"status": "ok", "service": "telesale-agent"}


@app.get("/health")
def health():
    if harness is None:
        raise HTTPException(status_code=503, detail="Agent is starting")
    return {"status": "ok"}
