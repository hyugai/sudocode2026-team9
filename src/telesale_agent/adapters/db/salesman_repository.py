"""Demo history reader. No agent execution, canonical memory reads or writes."""
import asyncio
from datetime import datetime, timezone
import unicodedata
from uuid import UUID

from sqlalchemy import case, inspect, select
from sqlalchemy.orm import sessionmaker

from telesale_agent.core.history import brief_preview, memory_preview
from .app_models import ChatMessage, Conversation, User
from .app_repository import AppDataNotFound, _page
from .checkpoint import CheckpointError, deserialize_checkpoint
from .voice_store import turns


def _date(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            value = None
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _normalize(value):
    return "".join(char for char in unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
                   if not unicodedata.combining(char))


def _voice_key(row):
    payload = row["payload"]
    sequence = payload.get("turn_number")
    return (_date(payload.get("created_at") or row["updated_at"]),
            sequence if type(sequence) is int else 0, row["source_id"])


def _ordered_turns(rows):
    if all(type(row["payload"].get("turn_number")) is int for row in rows):
        return sorted(rows, key=lambda row: (row["payload"]["turn_number"], _voice_key(row)))
    return sorted(rows, key=_voice_key)


class SalesmanRepository:
    def __init__(self, engine):
        self.engine = engine
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def _voice_rows(self, session, conversation_id=None):
        schema = self.engine.get_execution_options().get("schema_translate_map", {}).get(None)
        if not inspect(session.connection()).has_table(turns.name, schema=schema):
            return []  # Chat-only deployments do not require the optional voice journal.
        statement = select(turns)
        if conversation_id is not None:
            statement = statement.where(turns.c.payload["conversation_id"].as_string() == conversation_id)
        return [dict(row) for row in session.execute(statement).mappings()
                if isinstance(row["payload"], dict) and isinstance(row["payload"].get("conversation_id"), str)
                and row["payload"]["conversation_id"]]

    @staticmethod
    def _voice_item(conversation_id, rows, users):
        ordered = _ordered_turns(rows)
        owner_id = next((row["payload"].get("user_id") for row in ordered if row["payload"].get("user_id")), None)
        user = users.get(owner_id)
        last = ordered[-1]
        payload = last["payload"]
        return {
            "source": "voice", "id": conversation_id, "user_id": user["id"] if user else None,
            "user_name": user["name"] if user else None, "user_email": user["email"] if user else None,
            "customer_id": next((row["customer_id"] for row in reversed(ordered) if row["customer_id"]), None),
            "customer_phone": next((row["payload"].get("phone") for row in reversed(ordered) if row["payload"].get("phone")), None),
            "status": "interrupted" if payload.get("interrupted") or not payload.get("input_finished") else "saved",
            "turn_number": len(rows),
            "created_at": min(_date(row["payload"].get("created_at") or row["updated_at"]) for row in rows),
            "updated_at": max(_date(row["updated_at"]) for row in rows),
        }

    async def list(self, q="", source="all", limit=20, offset=0):
        _page(limit, offset)
        def read():
            with self.sessions() as session:
                items = []
                if source in ("all", "chat"):
                    statement = select(
                        Conversation.id, Conversation.customer_id, Conversation.status, Conversation.turn_number,
                        Conversation.created_at, Conversation.updated_at,
                        Conversation.checkpoint["state"]["identity"]["phone"].as_string().label("customer_phone"),
                        User.id.label("user_id"), User.name.label("user_name"), User.email.label("user_email"),
                    ).join(User, User.id == Conversation.user_id)
                    items.extend({**dict(row), "source": "chat"} for row in session.execute(statement).mappings())
                if source in ("all", "voice"):
                    users = {row.id: {"id": row.id, "name": row.name, "email": row.email}
                             for row in session.execute(select(User.id, User.name, User.email))}
                    grouped = {}
                    for row in self._voice_rows(session):
                        grouped.setdefault(row["payload"]["conversation_id"], []).append(row)
                    items.extend(self._voice_item(key, rows, users) for key, rows in grouped.items())
                query = _normalize(q.strip())
                if query:
                    items = [item for item in items if query in _normalize(" ".join(str(item.get(key) or "") for key in (
                        "user_name", "user_email", "customer_phone", "id", "customer_id")))]
                items.sort(key=lambda item: (_date(item["updated_at"]), item["source"], item["id"]), reverse=True)
                return {"items": items[offset:offset + limit], "total": len(items), "has_more": offset + limit < len(items)}
        return await asyncio.to_thread(read)

    async def get(self, source, conversation_id, limit=50, offset=0):
        _page(limit, offset)
        def read():
            with self.sessions() as session:
                if source == "chat":
                    row = session.get(Conversation, str(UUID(conversation_id)))
                    if row is None:
                        raise AppDataNotFound()
                    user = session.get(User, row.user_id)
                    owner = {"id": user.id, "name": user.name, "email": user.email}
                    try:
                        state = deserialize_checkpoint(row.checkpoint)
                        if state.conversation_id != row.id or state.turn_number != row.turn_number:
                            raise CheckpointError("Checkpoint không khớp phiên.")
                        memory = memory_preview(state) if row.turn_number else None
                    except CheckpointError:
                        memory = None
                    identity = (row.checkpoint or {}).get("state", {}) if isinstance(row.checkpoint, dict) else {}
                    identity = identity.get("identity") if isinstance(identity, dict) else None
                    messages = session.scalars(select(ChatMessage).where(ChatMessage.conversation_id == row.id).order_by(
                        ChatMessage.turn_number, case((ChatMessage.role == "user", 0), else_=1), ChatMessage.id
                    ).offset(offset).limit(limit + 1)).all()
                    return {
                        "id": row.id, "source": "chat", "status": row.status, "updated_at": row.updated_at,
                        "customer_id": row.customer_id, "customer_phone": identity.get("phone") if isinstance(identity, dict) else None,
                        "turn_number": row.turn_number, "user": owner, "call_brief": brief_preview(row.call_brief),
                        "memory": memory, "snapshot_at": row.updated_at if memory else None,
                        "messages": [{"id": message.id, "role": message.role, "content": message.content,
                                      "created_at": message.created_at} for message in messages[:limit]],
                        "has_more": len(messages) > limit, "next_offset": offset + min(limit, len(messages)),
                    }
                rows = _ordered_turns(self._voice_rows(session, conversation_id))
                if not rows:
                    raise AppDataNotFound()
                users = {row.id: {"id": row.id, "name": row.name, "email": row.email}
                         for row in session.execute(select(User.id, User.name, User.email))}
                item = self._voice_item(conversation_id, rows, users)
                messages = []
                brief = memory = snapshot_at = None
                for row in rows:
                    payload = row["payload"]
                    incomplete = bool(payload.get("interrupted") or not payload.get("input_finished"))
                    for role, field in (("user", "input_text"), ("agent", "output_text")):
                        if isinstance(payload.get(field), str) and payload[field]:
                            messages.append({"id": row["source_id"] + ":" + role, "role": role,
                                             "content": payload[field], "incomplete": incomplete,
                                             "created_at": _date(payload.get("created_at") or row["updated_at"])})
                    if not incomplete and payload.get("snapshot_at"):
                        candidate = memory_preview(payload.get("memory_snapshot"))
                        candidate_brief = brief_preview(payload.get("call_brief"))
                        if candidate is not None:
                            memory, snapshot_at = candidate, _date(payload["snapshot_at"])
                        if candidate_brief is not None:
                            brief = candidate_brief
                            if memory is None:
                                snapshot_at = _date(payload["snapshot_at"])
                return {**item, "user": users.get(item["user_id"]), "messages": messages[offset:offset + limit],
                        "call_brief": brief, "memory": memory, "snapshot_at": snapshot_at,
                        "has_more": offset + limit < len(messages), "next_offset": offset + len(messages[offset:offset + limit])}
        return await asyncio.to_thread(read)
