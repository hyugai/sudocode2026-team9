"""HTTP bootstrap and audio WebSocket; business logic stays in the controller."""
import asyncio
import logging
import os
import secrets
from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field
from telesale_agent.config.realtime import RealtimeSettings
from telesale_agent.application.conversation.services import ConversationServices
from telesale_agent.application.realtime.session import VoiceSessionManager
from telesale_agent.adapters.db.voice_store import VoiceStore
from .auth import COOKIE_NAME, get_auth_repository, require_user, require_customer, require_origin

logger = logging.getLogger(__name__)


class VoiceRequest(BaseModel):
    customer_phone: str | None = Field(default=None, max_length=30)


def create_voice_router(get_harness, *, manager_factory=None):
    router = APIRouter(prefix="/api/voice", tags=["voice"])
    manager = None

    async def get_manager():
        nonlocal manager
        settings = RealtimeSettings.from_env()
        if not settings.enabled:
            raise HTTPException(503, "Realtime voice chưa bật trên backend")
        harness = get_harness()
        if harness is None:
            raise HTTPException(503, "Agent chưa sẵn sàng")
        if manager is None:
            if manager_factory:
                manager = manager_factory(ConversationServices.from_harness(harness), settings)
            else:
                from telesale_agent.adapters.db.client import db_client
                manager = VoiceSessionManager(
                    ConversationServices.from_harness(harness), settings, VoiceStore(db_client.engine))
        return manager

    @router.get("/capabilities")
    async def capabilities():
        settings = RealtimeSettings.from_env()
        return {"enabled": settings.enabled, "model": settings.model,
                "tools_mode": settings.tools_mode, "protocol_version": 1,
                "requires_access_code": bool(os.getenv("API_KEY", "").strip())}

    @router.post("/sessions")
    async def create(request: Request, body: VoiceRequest, x_api_key: str | None = Header(default=None),
                     repository=Depends(get_auth_repository)):
        user = None
        if request.cookies.get(COOKIE_NAME) or request.headers.get("X-Conversation-Mode") == "account":
            require_origin(request)
            user = await require_user(request, repository)
            await require_customer(user)
        expected = os.getenv("API_KEY", "").strip()
        if user is None and expected and (not x_api_key or not secrets.compare_digest(expected, x_api_key)):
            raise HTTPException(401, "Invalid or missing API key")
        try:
            voice = await get_manager()
            creation = voice.create(body.customer_phone, user_id=user["id"]) if user else voice.create(body.customer_phone)
            result = await asyncio.wait_for(creation, timeout=45)
            return result
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(504, "Chuẩn bị phiên voice quá lâu; thử lại sau") from exc
        except Exception:
            logger.exception("Could not initialize realtime voice")
            raise HTTPException(503, "Không mở được realtime voice. Kiểm tra cấu hình và voice journal ở backend.")

    def authorize(voice, session_id, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing session token")
        try:
            return voice.owned(session_id, authorization[7:])
        except PermissionError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/sessions/{session_id}")
    async def status(session_id: str, authorization: str | None = Header(default=None)):
        voice = await get_manager()
        session = authorize(voice, session_id, authorization)
        return {"connected": session.connected, "finished": session.finished,
                "conversation_id": session.controller.state.conversation_id}

    @router.delete("/sessions/{session_id}")
    async def close(session_id: str, authorization: str | None = Header(default=None)):
        voice = await get_manager()
        session = authorize(voice, session_id, authorization)
        session.controller.closed = True
        session.controller.stop.set()
        return {"status": "closing"}

    @router.websocket("/sessions/{session_id}/stream")
    async def stream(websocket: WebSocket, session_id: str):
        session = None
        try:
            voice = await get_manager()
            if websocket.headers.get("origin") not in voice.settings.origins:
                await websocket.close(code=1008, reason="Origin not allowed")
                return
            await websocket.accept()
            hello = await asyncio.wait_for(websocket.receive_json(), timeout=10)
            if (hello.get("type") != "authenticate" or
                    not isinstance(hello.get("owner_token"), str) or
                    not isinstance(hello.get("connect_ticket"), str)):
                raise PermissionError("Invalid authentication message")
            session = voice.claim(session_id, hello["owner_token"], hello["connect_ticket"])
            session.runner = asyncio.current_task()
            await session.controller.run(websocket)
        except PermissionError:
            await websocket.close(code=1008, reason="Invalid or expired session")
        except Exception:
            logger.exception("Realtime voice connection ended")
            try:
                await websocket.send_json({"type": "error",
                    "detail": "Kết nối Gemini Live bị gián đoạn. Kiểm tra model/API key hoặc kết nối lại."})
            except Exception:
                pass
        finally:
            if session:
                session.connected, session.finished = False, True
                session.expires_at = 0
            try:
                await websocket.close()
            except Exception:
                pass

    async def shutdown():
        if manager:
            await manager.close()

    return router, shutdown
