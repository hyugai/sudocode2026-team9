import asyncio
import logging
import os
import re
import secrets
import json
import time
from uuid import UUID
from sqlalchemy.exc import SQLAlchemyError
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, Request
from pydantic import BaseModel, Field, field_validator
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder
import sys

# Add src to Python path so we can import the agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from telesale_agent.bootstrap import build_deepagent_harness_async
from telesale_agent.adapters.asr.config import ASRConfig
from telesale_agent.adapters.llm.rate_limits import is_rate_limit_error, provider_cooldown
from telesale_agent.core.errors import ASRUnavailableError, AudioInputError, AudioTooLargeError
from telesale_agent.core.models import CallBrief, Channel, TurnInput, ConversationState
from telesale_agent.adapters.rules.pii_utils import mask_pii
from contextlib import asynccontextmanager
from telesale_agent.adapters.db.app_repository import AppDataNotFound, AppDataRepository, ConversationConflict
from telesale_agent.adapters.db.checkpoint import CheckpointError
from telesale_agent.entrypoints.api.auth import COOKIE_NAME, auth_error, get_auth_repository, require_origin, require_user, require_customer

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
            if stream_tasks:
                await asyncio.gather(*stream_tasks, return_exceptions=True)
            await shutdown_voice()
        finally:
            print("🛑 Đóng kết nối MCP Servers...")
            if harness:
                await harness.__aexit__(None, None, None)

app = FastAPI(title="Telesale Agent API", lifespan=lifespan)

from telesale_agent.entrypoints.api.catalog import router as catalog_router
from telesale_agent.entrypoints.api.auth import router as auth_router
from telesale_agent.entrypoints.api.conversations import router as conversations_router
from telesale_agent.entrypoints.api.salesman import router as salesman_router
from telesale_agent.entrypoints.api.voice import create_voice_router
app.include_router(catalog_router)
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(salesman_router)
voice_router, shutdown_voice = create_voice_router(lambda: harness)
app.include_router(voice_router)


@app.middleware("http")
async def private_history_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/salesman/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class ArrivalTimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = scope["telesale_received_at"] = time.perf_counter()
        response_start = None

        async def emit(message):
            nonlocal response_start
            if (message["type"] == "http.response.start" and message["status"] == 200
                    and scope.get("path") in {"/api/chat", "/api/chat/audio"}
                    and any(key.lower() == b"content-type" and value.startswith(b"application/json")
                            for key, value in message["headers"])):
                response_start = message
                return
            if response_start is not None:
                if message["type"] == "http.response.body" and not message.get("more_body"):
                    payload = json.loads(message["body"])
                    latency = payload.get("latency", {})
                    if latency.get("measurement_mode") == "non_streaming":
                        backend_ms = (time.perf_counter() - started) * 1000
                        request_ms = round(max(0, backend_ms - (latency.get("asr_ms") or 0)), 3)
                        # Preserve the harness answer-ready timestamps. JSON
                        # delivery also waits for persistence and serialization.
                        latency.update(request_complete_ms=request_ms,
                                       backend_total_ms=round(backend_ms, 3))
                        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                        message = {**message, "body": body}
                        headers = [(key, value) for key, value in response_start["headers"] if key.lower() != b"content-length"]
                        response_start = {**response_start, "headers": [*headers, (b"content-length", str(len(body)).encode())]}
                await send(response_start)
                response_start = None
            await send(message)

        await self.app(scope, receive, emit)


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
stream_tasks: set[asyncio.Task] = set()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    configured = os.environ.get("API_KEY", "").strip()
    if configured and (
        x_api_key is None or not secrets.compare_digest(x_api_key, configured)
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

async def require_chat_access(request: Request, x_api_key: str | None = Header(default=None),
                              repository: AppDataRepository = Depends(get_auth_repository)) -> None:
    if request.cookies.get(COOKIE_NAME) or request.headers.get("X-Conversation-Mode") == "account":
        require_origin(request)
        user = await require_user(request, repository)
        await require_customer(user)
    else:
        require_api_key(x_api_key)


class ChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(max_length=10000)
    customer_phone: str | None = None

    @field_validator("conversation_id", "message")
    @classmethod
    def require_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

@app.post("/api/chat", dependencies=[Depends(require_chat_access)])
async def chat_endpoint(req: ChatRequest, request: Request, repository: AppDataRepository = Depends(get_auth_repository)):
    turn_input = TurnInput(
        conversation_id=req.conversation_id,
        text=req.message,
        customer_hint=req.customer_phone,
        metadata={"_latency_started_at": request.scope["telesale_received_at"]},
    )
    repository, user_id = await conversation_owner(request, req.conversation_id, repository)
    if "text/event-stream" in request.headers.get("accept", ""):
        return stream_chat_turn(turn_input, repository=repository, user_id=user_id)
    return await run_chat_turn(turn_input, repository=repository, user_id=user_id)


@app.post("/api/chat/audio", dependencies=[Depends(require_chat_access)])
async def audio_chat_endpoint(
    request: Request,
    conversation_id: str = Form(...),
    file: UploadFile = File(...),
    customer_phone: str | None = Form(default=None),
    repository: AppDataRepository = Depends(get_auth_repository),
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
        repository, user_id = await conversation_owner(request, conversation_id.strip(), repository)
        if "text/event-stream" in request.headers.get("accept", ""):
            return stream_chat_turn(turn_input, repository=repository, user_id=user_id)
        return await run_chat_turn(turn_input, repository=repository, user_id=user_id)
    finally:
        await file.close()


async def conversation_owner(request: Request, conversation_id: str, repository: AppDataRepository) -> tuple[AppDataRepository | None, str | None]:
    account = bool(request.cookies.get(COOKIE_NAME)) or request.headers.get("X-Conversation-Mode") == "account"
    if account:
        require_origin(request)
        user = await require_user(request, repository)
        return repository, user["id"]
    await guard_guest_id(conversation_id, repository)
    return None, None


async def guard_guest_id(conversation_id: str, repository: AppDataRepository) -> None:
    try:
        UUID(conversation_id)
    except ValueError:
        return  # Legacy guest IDs are allowed and cannot be account UUIDs.
    try:
        if await repository.conversation_exists(conversation_id):
            raise auth_error(404, "Không tìm thấy hội thoại.")
    except SQLAlchemyError as exc:
        raise auth_error(503, "Chưa kiểm tra được hội thoại. Hãy thử lại.") from exc


def stream_chat_turn(turn_input: TurnInput, *, repository=None, user_id=None) -> StreamingResponse:
    """Stream drafts, then one receipt after guardrails and the DB transaction."""
    async def events():
        queue = asyncio.Queue()
        connected = True
        latest_text, text_queued = "", False

        async def on_text(text):
            nonlocal latest_text, text_queued
            latest_text = text
            if connected and not text_queued:
                text_queued = True
                queue.put_nowait(("text", None))

        async def on_status(stage):
            if connected:
                queue.put_nowait(("status", {"stage": stage}))

        async def produce():
            try:
                result = await run_chat_turn(turn_input, repository=repository, user_id=user_id, on_text=on_text, on_status=on_status)
                if isinstance(result, JSONResponse):
                    data = json.loads(result.body)
                    event = "error" if result.status_code >= 400 else "done"
                    if event == "error":
                        data["status"] = result.status_code
                else:
                    event, data = "done", result
                if connected:
                    queue.put_nowait((event, data))
            except HTTPException as exc:
                if connected:
                    queue.put_nowait(("error", {"detail": exc.detail, "status": exc.status_code}))
            except Exception:
                logger.exception("Chat stream failed: %s", turn_input.conversation_id)
                if connected:
                    queue.put_nowait(("error", {"detail": "Kết nối bị gián đoạn. Hãy kiểm tra lịch sử trước khi gửi lại."}))

        # Finish the current turn/save even if the browser disconnects; never replay it.
        task = asyncio.create_task(produce())
        stream_tasks.add(task)
        task.add_done_callback(stream_tasks.discard)
        try:
            yield 'event: status\ndata: {"stage":"processing"}\n\n'
            while True:
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event == "text":
                    text_queued = False
                    data = {"text": latest_text}
                yield f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"
                if event in {"done", "error"}:
                    break
        finally:
            connected = False

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"})


async def run_chat_turn(turn_input: TurnInput, *, repository: AppDataRepository | None = None, user_id: str | None = None, on_text=None, on_status=None):
    """Keep text and voice turns in the same ordered conversation."""
    if harness is None:
        raise HTTPException(status_code=503, detail="Agent is not ready")

    conversation_id = turn_input.conversation_id
    if repository is not None:
        try:
            conversation_id = turn_input.conversation_id = str(UUID(conversation_id))
        except ValueError as exc:
            raise auth_error(422, "Mã hội thoại không hợp lệ.") from exc
    lock = session_locks.setdefault(conversation_id, asyncio.Lock())

    async with lock:
        if provider_cooldown.remaining():
            return rate_limit_response()
        if repository is not None:
            try:
                state = await repository.load_state(user_id, conversation_id, active_only=True)
            except AppDataNotFound as exc:
                raise auth_error(404, "Không tìm thấy hội thoại.") from exc
            except (CheckpointError, ConversationConflict) as exc:
                raise auth_error(409, str(exc)) from exc
            except SQLAlchemyError as exc:
                raise auth_error(503, "Chưa đọc được hội thoại. Hãy thử lại.") from exc
        else:
            state = sessions.get(conversation_id) or ConversationState(conversation_id=conversation_id)
        try:
            result = (await harness.run_turn(turn_input, state, on_text=on_text, on_status=on_status)
                      if on_text is not None else await harness.run_turn(turn_input, state))
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
        payload = turn_payload(turn_input, result)
        if repository is not None:
            try:
                if on_status:
                    await on_status("saving")
                payload.update(await repository.save_turn(user_id, result.state, turn_input.text,
                                                         result.response_text, payload["call_brief"]))
            except Exception:
                logger.exception("Could not persist account conversation %s", conversation_id)
                sessions.pop(conversation_id, None)
                return JSONResponse(status_code=502, headers={"Cache-Control": "no-store"}, content={
                    "detail": "Chưa xác nhận lưu được kết quả. Hãy kiểm tra lịch sử trước khi gửi lại.",
                    "code": "turn_outcome_unknown",
                })
        sessions[conversation_id] = result.state

    return JSONResponse(content=jsonable_encoder(payload), headers={"Cache-Control": "no-store"}) if repository else payload


def _call_brief_preview(brief: CallBrief | None) -> dict[str, str | list[str]] | None:
    """Customer-facing compact view; exclude identifiers and raw CRM/memory."""
    if brief is None:
        return None
    def display_text(value: str, limit: int) -> str:
        # Currency facts are numbers, not identity documents. Keep their exact
        # values while applying the existing PII rules to surrounding prose.
        parts = re.split(
            r"(\b(?:budget_vnd|price_vnd|price_quoted_vnd|previous_price_quoted_vnd):\s*\d+(?:\.\d+)?)",
            value,
        )
        return "".join(part if index % 2 else mask_pii(part)[0]
                       for index, part in enumerate(parts))[:limit]

    return {
        "summary": display_text(brief.summary, 4000),
        "needs": [display_text(item, 1000) for item in brief.needs[:12]],
        "objections": [display_text(item, 1000) for item in brief.objections[:12]],
        "unresolved_issues": [display_text(item, 1000) for item in brief.unresolved_issues[:12]],
    }


def turn_payload(turn_input, result):
    response = {"response": result.response_text, "latency": getattr(result, "latency", {})}
    response["call_brief"] = _call_brief_preview(getattr(result, "call_brief", None))
    response["call_brief_latency_ms"] = response["latency"].get("call_brief_ms")
    if turn_input.channel == Channel.VOICE:
        response["transcript"] = turn_input.text
    else:
        response["normalized_message"] = turn_input.text
    if provider_cooldown.remaining():
        response["retry_after_seconds"] = provider_cooldown.remaining()
    if os.environ.get("ENABLE_DEBUG_RESPONSE", "false").lower() == "true":
        response["debug"] = {
            "call_brief": response["call_brief"],
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
async def clear_session(conversation_id: str, request: Request, repository: AppDataRepository = Depends(get_auth_repository)):
    if request.cookies.get(COOKIE_NAME) or request.headers.get("X-Conversation-Mode") == "account":
        user = await require_user(request, repository)
        await require_customer(user)
    await guard_guest_id(conversation_id, repository)
    sessions.pop(conversation_id, None)
    session_locks.pop(conversation_id, None)
    return {"status": "cleared", "conversation_id": conversation_id}

# Optional root endpoint for health checks
@app.get("/")
def read_root():
    return {"status": "ok", "service": "telesale-agent"}


@app.get("/health")
@app.get("/api/health")
def health():
    if harness is None:
        raise HTTPException(status_code=503, detail="Agent is starting")
    return {"status": "ok"}
