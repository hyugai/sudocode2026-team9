"""Bounded single-worker session registry, with scoped bearer tokens and WS tickets."""
import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass
from uuid import uuid4
from sqlalchemy import text
from telesale_agent.adapters.llm.gemini_live import GeminiLiveClient
from telesale_agent.application.realtime.context import instructions, tool_declarations
from telesale_agent.application.realtime.controller import (
    VoiceSessionController, initialize_customer, recover_memory,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class Session:
    controller: VoiceSessionController
    owner_hash: str
    ticket_hash: str
    expires_at: float
    connected: bool = False
    finished: bool = False
    runner: object = None


class VoiceSessionManager:
    def __init__(self, services, settings, store, model_factory=GeminiLiveClient):
        self.services, self.settings, self.store = services, settings, store
        self.model_factory = model_factory
        self.sessions = {}
        self.lock = asyncio.Lock()
        self.lease = None
        self.initialized = False

    async def initialize(self):
        if self.initialized:
            return
        await self.store.ready()
        # Prevent two production workers from sharing file memory without a distributed writer.
        if self.store.engine.dialect.name == "postgresql" and self.lease is None:
            def lease():
                connection = self.store.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
                acquired = connection.execute(text("SELECT pg_try_advisory_lock(1826417821)")).scalar()
                if not acquired:
                    connection.close()
                    raise RuntimeError("Realtime voice yêu cầu một backend worker")
                return connection
            self.lease = await asyncio.to_thread(lease)
        await recover_memory(self.services, self.store)
        self.initialized = True

    async def create(self, phone):
        async with self.lock:
            await self.initialize()
            now = time.monotonic()
            for key, session in list(self.sessions.items()):
                if not session.connected and session.expires_at < now:
                    del self.sessions[key]
            if len(self.sessions) >= self.settings.max_sessions:
                raise ValueError("Hệ thống đang đủ phiên realtime; thử lại sau")
            session_id, owner, ticket = uuid4().hex, secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            conversation_id = "live-" + session_id
            state, context = await initialize_customer(self.services, conversation_id, phone)
            model = self.model_factory(
                self.settings, instructions(state),
                tool_declarations(self.services.mcp_tools, self.settings.tools_mode))
            controller = VoiceSessionController(
                self.services, self.settings, model, self.store, state, context, phone)
            self.sessions[session_id] = Session(
                controller, digest(owner), digest(ticket), now + 120)
            return {"session_id": session_id, "conversation_id": conversation_id,
                    "owner_token": owner, "connect_ticket": ticket, "protocol_version": 1}

    def owned(self, session_id, owner):
        session = self.sessions.get(session_id)
        if not session or not secrets.compare_digest(session.owner_hash, digest(owner)):
            raise PermissionError("Phiên realtime không tồn tại hoặc không thuộc kết nối này")
        return session

    def claim(self, session_id, owner, ticket):
        session = self.owned(session_id, owner)
        if (session.finished or session.controller.closed or session.connected or time.monotonic() > session.expires_at
                or not secrets.compare_digest(session.ticket_hash, digest(ticket))):
            raise PermissionError("Ticket realtime đã hết hạn hoặc đã sử dụng")
        session.connected = True
        session.ticket_hash = ""
        return session

    async def close(self):
        for session in list(self.sessions.values()):
            session.controller.closed = True
            session.controller.stop.set()
        runners = [s.runner for s in self.sessions.values() if s.runner and not s.runner.done()]
        if runners:
            try:
                await asyncio.wait_for(asyncio.gather(*runners, return_exceptions=True), 45)
            except TimeoutError:
                pass  # Prepared journal jobs are recovered at the next initialization.
        if self.lease:
            lease, self.lease = self.lease, None
            def release():
                try:
                    lease.execute(text("SELECT pg_advisory_unlock(1826417821)"))
                finally:
                    lease.close()
            await asyncio.to_thread(release)
