"""Application accounts and chat history; separate from catalog/voice tables."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint, Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from .models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(100), nullable=False)
    email = Column(String(254), nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    role = Column(String(16), nullable=False, default="user", server_default="user")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("role IN ('user', 'salesman')", name="ck_users_role"),
        CheckConstraint("email = lower(trim(email)) AND length(email) > 0", name="ck_users_email"),
        CheckConstraint("length(trim(name)) > 0", name="ck_users_name"),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(String(50), ForeignKey("customers.customer_id", ondelete="SET NULL"))
    status = Column(String(16), nullable=False, default="active", server_default="active")
    turn_number = Column(Integer, nullable=False, default=0, server_default="0")
    call_brief = Column(JSONB)
    checkpoint = Column(JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    ended_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('active', 'ended')", name="ck_conversations_status"),
        CheckConstraint("turn_number >= 0", name="ck_conversations_turn"),
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )


class ChatMessage(Base):
    __tablename__ = "messages"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    conversation_id = Column(Uuid(as_uuid=False), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    turn_number = Column(Integer, nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("role IN ('user', 'agent')", name="ck_messages_role"),
        CheckConstraint("turn_number > 0", name="ck_messages_turn"),
        UniqueConstraint("conversation_id", "turn_number", "role", name="uq_messages_turn_role"),
    )


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    message_id = Column(Uuid(as_uuid=False), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = Column(String(16))
    comment = Column(String(1000), nullable=False, default="", server_default="")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("rating IS NULL OR rating IN ('positive', 'negative')", name="ck_feedback_rating"),
        UniqueConstraint("message_id", "user_id", name="uq_feedback_message_user"),
    )


# Pass this explicit list to migrations: never create/drop all catalog metadata.
APP_TABLES = tuple(model.__table__ for model in (
    User, AuthSession, Conversation, ChatMessage, MessageFeedback,
))
