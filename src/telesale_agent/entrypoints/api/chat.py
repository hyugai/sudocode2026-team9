import asyncio
import logging
import os
import secrets
import json
import time
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, Request
from pydantic import BaseModel, field_validator
from fastapi.responses import JSONResponse, StreamingResponse
import sys

# Add src to Python path so we can import the agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from telesale_agent.bootstrap import build_deepagent_harness_async
from telesale_agent.adapters.asr.config import ASRConfig
from telesale_agent.adapters.llm.rate_limits import is_rate_limit_error, provider_cooldown
from telesale_agent.core.errors import ASRUnavailableError, AudioInputError, AudioTooLargeError
from telesale_agent.core.models import Channel, TurnInput, ConversationState
from contextlib import asynccontextmanager
from telesale_agent.application.deepagent.streaming import stream_events

# Global harness reference
harness = None
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global harness
    print("🚀 Khởi tạo kết nối MCP Servers cho API Backend...")
    harness = await build_deepagent_harness_async()
    try:
        yield
    finally:
        try:
            await shutdown_voice()
        finally:
            print("🛑 Đóng kết nối MCP Servers...")
            if harness:
                await harness.__aexit__(None, None, None)

app = FastAPI(title="Telesale Agent API", lifespan=lifespan)

from telesale_agent.entrypoints.api.voice import create_voice_router
voice_router, shutdown_voice = create_voice_router(lambda: harness)
app.include_router(voice_router)


class ArrivalTimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope["telesale_received_at"] = time.perf_counter()
        await self.app(scope, receive, send)


app.add_middleware(ArrivalTimingMiddleware)

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
    expose_headers=["Retry-After"],
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
    stream: bool = False

    @field_validator("conversation_id", "message")
    @classmethod
    def require_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

@app.post("/api/chat", dependencies=[Depends(require_api_key)])
async def chat_endpoint(req: ChatRequest, request: Request):
    turn_input = TurnInput(
        conversation_id=req.conversation_id,
        text=req.message,
        customer_hint=req.customer_phone,
        metadata={"_latency_started_at": request.scope["telesale_received_at"]},
    )
    if req.stream:
        return streaming_chat_turn(turn_input)
    return await run_chat_turn(turn_input)


@app.post("/api/chat/audio", dependencies=[Depends(require_api_key)])
async def audio_chat_endpoint(
    request: Request,
    conversation_id: str = Form(...),
    file: UploadFile = File(...),
    customer_phone: str | None = Form(default=None),
    stream: bool = Form(default=False),
):
    try:
        if harness is None:
            raise HTTPException(status_code=503, detail="Agent is not ready")
        if not conversation_id.strip():
            raise HTTPException(status_code=422, detail="conversation_id must not be empty")
        config = getattr(getattr(harness, "asr", None), "config", None) or ASRConfig.from_env()
        # Bound the in-memory read even if the client lies about its file size.
        if file.size is not None and file.size > config.max_upload_bytes:
            raise HTTPException(status_code=413, detail="File ghi âm vượt quá dung lượng cho phép.")
        audio = await file.read(config.max_upload_bytes + 1)
        if len(audio) > config.max_upload_bytes:
            raise HTTPException(status_code=413, detail="File ghi âm vượt quá dung lượng cho phép.")
        if not audio:
            raise HTTPException(status_code=422, detail="File ghi âm rỗng.")
        turn_input = TurnInput(
            conversation_id=conversation_id.strip(),
            audio=audio,
            channel=Channel.VOICE,
            customer_hint=customer_phone or None,
            metadata={"_latency_started_at": request.scope["telesale_received_at"], "offline_audio": True},
        )
        if stream:
            return streaming_chat_turn(turn_input)
        return await run_chat_turn(turn_input)
    finally:
        await file.close()


async def run_chat_turn(turn_input: TurnInput):
    """Keep text and voice turns in the same ordered conversation."""
    if harness is None:
        raise HTTPException(status_code=503, detail="Agent is not ready")

    conversation_id = turn_input.conversation_id
    lock = session_locks.setdefault(conversation_id, asyncio.Lock())

    async with lock:
        if provider_cooldown.remaining():
            return rate_limit_response()
        state = sessions.get(conversation_id) or ConversationState(
            conversation_id=conversation_id
        )
        try:
            result = await harness.run_turn(turn_input, state)
        except AudioTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except AudioInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ASRUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            # Return a handled response so CORS still applies. An uncaught
            # provider error otherwise appears as "Failed to fetch" in the web UI.
            if is_rate_limit_error(exc):
                provider_cooldown.record(exc)
                logger.warning("Provider rate limit for conversation %s; cooldown %ss", conversation_id, provider_cooldown.remaining())
                return rate_limit_response()
            logger.exception("Conversation turn failed: %s", conversation_id)
            raise HTTPException(
                status_code=502,
                detail="Không thể xử lý lượt hội thoại lúc này. Vui lòng thử lại sau.",
            ) from exc
        sessions[conversation_id] = result.state

    return turn_payload(turn_input, result)


def turn_payload(turn_input, result):
    response = {"response": result.response_text, "latency": getattr(result, "latency", {})}
    if turn_input.channel == Channel.VOICE:
        response["transcript"] = turn_input.text
    else:
        response["normalized_message"] = turn_input.text
    if provider_cooldown.remaining():
        response["retry_after_seconds"] = provider_cooldown.remaining()
    if os.environ.get("ENABLE_DEBUG_RESPONSE", "false").lower() == "true":
        response["debug"] = {
            "raw_asr_transcript": turn_input.metadata.get("raw_asr_transcript"),
            "raw_user_text": turn_input.metadata.get("raw_user_text"),
            "normalized_input": turn_input.text,
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


def streaming_chat_turn(turn_input):
    if harness is None:
        raise HTTPException(status_code=503, detail="Agent is not ready")
    if provider_cooldown.remaining():
        return rate_limit_response()

    async def execute(output):
        conversation_id = turn_input.conversation_id
        lock = session_locks.setdefault(conversation_id, asyncio.Lock())
        # The producer owns this lock even after a client disconnects.
        async with lock:
            if provider_cooldown.remaining():
                raise HTTPException(status_code=429, detail="Dịch vụ đang giới hạn token.")
            state = sessions.get(conversation_id) or ConversationState(conversation_id)
            result = await harness.run_turn(turn_input, state, response_stream=output)
            sessions[conversation_id] = result.state
            return result

    async def body():
        async for event in stream_events(execute, started_at=turn_input.metadata["_latency_started_at"]):
            if event["type"] == "complete":
                payload = {"type": "complete", **turn_payload(turn_input, event["result"])}
            elif event["type"] == "error":
                exc = event["exception"]
                if is_rate_limit_error(exc):
                    provider_cooldown.record(exc)
                logger.error("Streaming turn failed: %s", type(exc).__name__)
                detail = "Không thể hoàn tất lượt hội thoại. Vui lòng kiểm tra kết nối trước khi gửi lại."
                if isinstance(exc, (AudioInputError, ASRUnavailableError, AudioTooLargeError)):
                    detail = str(exc)
                payload = {"type": "error", "detail": detail,
                           "retry_after_seconds": provider_cooldown.remaining()}
            else:
                payload = event
            yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

    return StreamingResponse(body(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


def rate_limit_response() -> JSONResponse:
    seconds = max(1, provider_cooldown.remaining())
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Dịch vụ hội thoại đang giới hạn token. Vui lòng chờ {seconds} giây rồi gửi lại.",
            "retry_after_seconds": seconds,
        },
        headers={"Retry-After": str(seconds)},
    )


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
