"""Versioned, bounded JSON snapshots of the application's ConversationState."""

import json
from dataclasses import asdict, fields
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from telesale_agent.core.models import (
    CallBrief, ConversationState, CustomerIdentity, Message, RetrievedContext,
)

MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024


class CheckpointError(ValueError):
    """A snapshot cannot safely be used to continue the conversation."""


class CheckpointTooLargeError(CheckpointError):
    pass


class _Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    state: ConversationState


def _require_fields(value: Any, model: type) -> None:
    if not isinstance(value, dict) or set(value) != {item.name for item in fields(model)}:
        raise CheckpointError("Checkpoint thiếu hoặc thừa trường dữ liệu.")


def _decode(payload: Any) -> tuple[dict[str, Any], ConversationState]:
    if not isinstance(payload, dict) or set(payload) != {"version", "state"}:
        raise CheckpointError("Checkpoint không hợp lệ.")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise CheckpointError("Phiên bản checkpoint chưa được hỗ trợ.")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
            raise CheckpointTooLargeError("Hội thoại quá lớn. Hãy tạo hội thoại mới.")
        raw = payload["state"]
        _require_fields(raw, ConversationState)
        for name, model in (("identity", CustomerIdentity), ("retrieved_data", RetrievedContext), ("call_brief", CallBrief)):
            if raw[name] is not None:
                _require_fields(raw[name], model)
        if not isinstance(raw["messages"], list):
            raise CheckpointError("Danh sách tin nhắn không hợp lệ.")
        for message in raw["messages"]:
            _require_fields(message, Message)
        state = _Checkpoint.model_validate_json(encoded, strict=True).state
        if not state.conversation_id.strip() or state.turn_number < 0:
            raise CheckpointError("Định danh hoặc số lượt không hợp lệ.")
        if any(message.role not in {"user", "customer", "agent"} for message in state.messages):
            raise CheckpointError("Vai trò tin nhắn không hợp lệ.")
        return json.loads(encoded), state
    except (TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, CheckpointError):
            raise
        raise CheckpointError("Không đọc được checkpoint. Hãy tạo hội thoại mới.") from exc


def serialize_checkpoint(state: ConversationState) -> dict[str, Any]:
    """Return an independent JSON-compatible snapshot; never truncate state."""
    if not isinstance(state, ConversationState):
        raise CheckpointError("State phải là ConversationState.")
    try:
        return _decode({"version": 1, "state": asdict(state)})[0]
    except (TypeError, RecursionError) as exc:
        raise CheckpointError("State chứa dữ liệu không thể lưu thành JSON.") from exc


def deserialize_checkpoint(payload: Any) -> ConversationState:
    """Restore nested dataclasses with strict types and no pickle/coercion."""
    return _decode(payload)[1]
