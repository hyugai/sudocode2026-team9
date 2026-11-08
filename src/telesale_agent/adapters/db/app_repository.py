"""Small async facade over synchronous PostgreSQL sessions.

Each operation creates/closes its own Session inside asyncio.to_thread. Returned
values are plain data, never ORM instances or database sessions.
"""

import asyncio
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from telesale_agent.core.models import ConversationState
from .app_models import AuthSession, ChatMessage, Conversation, MessageFeedback, User, utc_now
from .checkpoint import CheckpointError, deserialize_checkpoint, serialize_checkpoint


class AppDataNotFound(LookupError):
    """Missing or not owned: deliberately use the same error for both."""


class ConversationConflict(ValueError):
    pass


def _uuid(value: str) -> str:
    return str(UUID(value))


def _text(value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Nội dung phải có từ 1 đến {limit} ký tự.")
    return value.strip()


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("limit phải từ 1–100, offset không âm.")


def _user(row: User) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "email": row.email}


def _conversation(row: Conversation) -> dict[str, Any]:
    return {"id": row.id, "status": row.status, "turn_number": row.turn_number,
            "created_at": row.created_at, "updated_at": row.updated_at, "ended_at": row.ended_at}


def _owned(session: Session, user_id: str, conversation_id: str, *, lock: bool = False) -> Conversation:
    statement = select(Conversation).where(
        Conversation.id == _uuid(conversation_id), Conversation.user_id == _uuid(user_id))
    row = session.scalar(statement.with_for_update() if lock else statement)
    if row is None:
        raise AppDataNotFound("Không tìm thấy hội thoại.")
    return row


def _brief_preview(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"summary", "needs", "objections", "unresolved_issues"}:
        raise ValueError("Call brief chỉ nhận các trường preview.")
    if not isinstance(value["summary"], str) or len(value["summary"]) > 4000:
        raise ValueError("Tóm tắt call brief không hợp lệ.")
    result = {"summary": value["summary"]}
    for key in ("needs", "objections", "unresolved_issues"):
        items = value[key]
        if not isinstance(items, list) or len(items) > 12 or any(
            not isinstance(item, str) or len(item) > 1000 for item in items
        ):
            raise ValueError("Danh sách call brief không hợp lệ.")
        result[key] = list(items)
    return result


class AppDataRepository:
    def __init__(self, engine: Engine):
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)

    async def create_user(self, name: str, email: str, password_hash: str) -> dict[str, Any]:
        def write():
            with self.sessions.begin() as session:
                row = User(name=_text(name, 100), email=_text(email, 254).lower(),
                           password_hash=_text(password_hash, 1000))
                session.add(row)
                session.flush()
                return _user(row)
        return await asyncio.to_thread(write)

    async def find_user_credentials(self, email: str) -> dict[str, Any] | None:
        """Internal auth lookup only; callers must never expose password_hash."""
        def read():
            with self.sessions() as session:
                row = session.scalar(select(User).where(User.email == _text(email, 254).lower()))
                return {**_user(row), "password_hash": row.password_hash} if row else None
        return await asyncio.to_thread(read)

    async def create_auth_session(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        def write():
            if not re.fullmatch(r"[0-9a-f]{64}", token_hash):
                raise ValueError("Chỉ lưu SHA-256 token hash dạng hex.")
            if expires_at.tzinfo is None or expires_at.utcoffset() is None or expires_at <= utc_now():
                raise ValueError("Session cần thời hạn tương lai có timezone.")
            with self.sessions.begin() as session:
                session.add(AuthSession(user_id=_uuid(user_id), token_hash=token_hash, expires_at=expires_at))
        await asyncio.to_thread(write)

    async def get_session_user(self, token_hash: str) -> dict[str, Any] | None:
        def read():
            with self.sessions() as session:
                row = session.scalar(select(User).join(AuthSession, AuthSession.user_id == User.id).where(
                    AuthSession.token_hash == token_hash, AuthSession.expires_at > utc_now()))
                return _user(row) if row else None
        return await asyncio.to_thread(read)

    async def delete_auth_session(self, token_hash: str) -> None:
        def write():
            with self.sessions.begin() as session:
                session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))
        await asyncio.to_thread(write)

    async def create_conversation(self, user_id: str, customer_id: str | None = None) -> dict[str, Any]:
        def write():
            with self.sessions.begin() as session:
                row = Conversation(user_id=_uuid(user_id), customer_id=customer_id)
                session.add(row)
                session.flush()
                row.checkpoint = serialize_checkpoint(ConversationState(conversation_id=row.id))
                return _conversation(row)
        return await asyncio.to_thread(write)

    async def conversation_exists(self, conversation_id: str) -> bool:
        """Used to prevent guest chat/clear from reusing an account's ID."""
        def read():
            with self.sessions() as session:
                return session.scalar(select(Conversation.id).where(Conversation.id == _uuid(conversation_id))) is not None
        return await asyncio.to_thread(read)

    async def list_conversations(self, user_id: str, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        def read():
            _page(limit, offset)
            with self.sessions() as session:
                rows = session.scalars(select(Conversation).where(Conversation.user_id == _uuid(user_id))
                    .order_by(Conversation.updated_at.desc(), Conversation.id.desc()).offset(offset).limit(limit + 1)).all()
                return {"items": [_conversation(row) for row in rows[:limit]], "has_more": len(rows) > limit}
        return await asyncio.to_thread(read)

    async def get_conversation(self, user_id: str, conversation_id: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        def read():
            _page(limit, offset)
            with self.sessions() as session:
                row = _owned(session, user_id, conversation_id)
                messages = session.execute(select(ChatMessage, MessageFeedback).outerjoin(MessageFeedback,
                    (MessageFeedback.message_id == ChatMessage.id) & (MessageFeedback.user_id == row.user_id))
                    .where(ChatMessage.conversation_id == row.id)
                    .order_by(ChatMessage.turn_number, case((ChatMessage.role == "user", 0), else_=1))
                    .offset(offset).limit(limit + 1)).all()
                items = [{"id": message.id, "role": message.role, "content": message.content,
                          "turn_number": message.turn_number, "created_at": message.created_at,
                          "feedback": {"rating": feedback.rating, "comment": feedback.comment} if feedback else None}
                         for message, feedback in messages[:limit]]
                return {**_conversation(row), "messages": items, "call_brief": row.call_brief,
                        "has_more": len(messages) > limit}
        return await asyncio.to_thread(read)

    async def load_state(self, user_id: str, conversation_id: str) -> ConversationState:
        def read():
            with self.sessions() as session:
                row = _owned(session, user_id, conversation_id)
                state = deserialize_checkpoint(row.checkpoint)
                if state.conversation_id != row.id or state.turn_number != row.turn_number:
                    raise CheckpointError("Checkpoint không khớp hội thoại đã lưu.")
                return state
        return await asyncio.to_thread(read)

    async def save_turn(self, user_id: str, state: ConversationState, user_text: str,
                        response_text: str, call_brief: dict[str, Any] | None) -> dict[str, Any]:
        """Only call after the harness; all four changes commit or roll back together."""
        def write():
            _text(user_text, 10000)
            if not isinstance(response_text, str) or not response_text.strip():
                raise ValueError("Câu trả lời không được rỗng.")
            checkpoint = serialize_checkpoint(state)
            preview = _brief_preview(call_brief)
            if len(state.messages) < 2 or [(m.role, m.content) for m in state.messages[-2:]] != [
                ("user", user_text), ("agent", response_text)
            ]:
                raise ValueError("Tin nhắn lưu phải khớp lượt cuối của checkpoint.")
            with self.sessions.begin() as session:
                row = _owned(session, user_id, state.conversation_id, lock=True)
                if row.status != "active" or state.turn_number != row.turn_number + 1:
                    raise ConversationConflict("Hội thoại đã kết thúc hoặc số lượt không khớp.")
                customer_id = state.identity.customer_id if state.identity else None
                if row.customer_id is not None and customer_id != row.customer_id:
                    raise ConversationConflict("Không được đổi khách hàng của hội thoại.")
                if customer_id is not None:
                    row.customer_id = customer_id
                user_message = ChatMessage(conversation_id=row.id, turn_number=state.turn_number,
                                           role="user", content=user_text)
                agent_message = ChatMessage(conversation_id=row.id, turn_number=state.turn_number,
                                            role="agent", content=response_text)
                session.add_all([user_message, agent_message])
                row.checkpoint, row.call_brief = checkpoint, preview
                row.turn_number, row.updated_at = state.turn_number, utc_now()
                session.flush()
                return {"conversation_id": row.id, "turn_number": row.turn_number,
                        "user_message_id": user_message.id, "message_id": agent_message.id}
        return await asyncio.to_thread(write)

    async def end_conversation(self, user_id: str, conversation_id: str) -> None:
        def write():
            with self.sessions.begin() as session:
                row = _owned(session, user_id, conversation_id, lock=True)
                if row.status != "ended":
                    row.status, row.ended_at = "ended", utc_now()
                    row.updated_at = row.ended_at
        await asyncio.to_thread(write)

    @staticmethod
    def _feedback_target(session: Session, user_id: str, message_id: str) -> ChatMessage:
        # Lock the parent too, so concurrent PUT/DELETE serialize before upsert.
        row = session.scalar(select(ChatMessage).join(Conversation,
            Conversation.id == ChatMessage.conversation_id).where(
            ChatMessage.id == _uuid(message_id), Conversation.user_id == _uuid(user_id),
            ChatMessage.role == "agent").with_for_update(of=Conversation))
        if row is None:
            raise AppDataNotFound("Không tìm thấy câu trả lời.")
        return row

    async def put_feedback(self, user_id: str, message_id: str, rating: str | None, comment: str) -> dict[str, Any]:
        def write():
            if rating not in (None, "positive", "negative") or not isinstance(comment, str) or len(comment) > 1000:
                raise ValueError("Rating hoặc góp ý không hợp lệ.")
            with self.sessions.begin() as session:
                message = self._feedback_target(session, user_id, message_id)
                row = session.scalar(select(MessageFeedback).where(
                    MessageFeedback.message_id == message.id, MessageFeedback.user_id == _uuid(user_id)))
                if row is None:
                    row = MessageFeedback(message_id=message.id, user_id=_uuid(user_id))
                    session.add(row)
                row.rating, row.comment, row.updated_at = rating, comment.strip(), utc_now()
                return {"message_id": message.id, "rating": row.rating, "comment": row.comment}
        return await asyncio.to_thread(write)

    async def delete_feedback(self, user_id: str, message_id: str) -> None:
        def write():
            with self.sessions.begin() as session:
                message = self._feedback_target(session, user_id, message_id)
                session.execute(delete(MessageFeedback).where(
                    MessageFeedback.message_id == message.id, MessageFeedback.user_id == _uuid(user_id)))
        await asyncio.to_thread(write)
