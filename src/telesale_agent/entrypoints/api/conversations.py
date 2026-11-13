"""Account-owned conversation history and per-reply feedback."""

from collections.abc import AsyncIterator
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from telesale_agent.adapters.db.app_repository import AppDataNotFound, AppDataRepository, ConversationConflict
from telesale_agent.adapters.db.checkpoint import CheckpointError, CheckpointTooLargeError
from .auth import NO_STORE, auth_error, get_auth_repository, require_origin, require_customer


def no_store(response: Response) -> None:
    response.headers.update(NO_STORE)


async def repository_dependency(repository: AppDataRepository = Depends(get_auth_repository)) -> AsyncIterator[AppDataRepository]:
    try:
        yield repository
    except AppDataNotFound as exc:
        raise auth_error(404, "Không tìm thấy hội thoại hoặc câu trả lời.") from exc
    except CheckpointTooLargeError as exc:
        raise auth_error(413, str(exc)) from exc
    except (ConversationConflict, CheckpointError) as exc:
        raise auth_error(409, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise auth_error(503, "Chưa kết nối được dữ liệu hội thoại. Hãy thử lại.") from exc
    except ValueError as exc:
        raise auth_error(422, "Thông tin hội thoại hoặc góp ý không hợp lệ.") from exc


router = APIRouter(prefix="/api", tags=["conversations"], dependencies=[Depends(no_store)])


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_phone: str | None = Field(default=None, max_length=30)


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["positive", "negative"] | None = None
    comment: str = Field(default="", max_length=1000)


@router.post("/conversations", status_code=201, dependencies=[Depends(require_origin)])
async def create_conversation(body: CreateConversation, user: dict = Depends(require_customer),
                              repository: AppDataRepository = Depends(repository_dependency)):
    # The phone is supplied again with the first chat turn; CRM identity is resolved by the agent.
    return await repository.create_conversation(user["id"])


@router.get("/conversations")
async def list_conversations(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                             user: dict = Depends(require_customer), repository: AppDataRepository = Depends(repository_dependency)):
    return await repository.list_conversations(user["id"], limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: UUID, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                           user: dict = Depends(require_customer), repository: AppDataRepository = Depends(repository_dependency)):
    return await repository.get_conversation(user["id"], str(conversation_id), limit=limit, offset=offset)


@router.post("/conversations/{conversation_id}/end", dependencies=[Depends(require_origin)])
async def end_conversation(conversation_id: UUID, user: dict = Depends(require_customer),
                           repository: AppDataRepository = Depends(repository_dependency)):
    import asyncio
    from . import chat
    key = str(conversation_id)
    async with chat.session_locks.setdefault(key, asyncio.Lock()):
        await repository.end_conversation(user["id"], key)
        chat.sessions.pop(key, None)
    return {"status": "ended"}


@router.put("/messages/{message_id}/feedback", dependencies=[Depends(require_origin)])
async def put_feedback(message_id: UUID, body: FeedbackInput, user: dict = Depends(require_customer),
                       repository: AppDataRepository = Depends(repository_dependency)):
    return await repository.put_feedback(user["id"], str(message_id), body.rating, body.comment)


@router.delete("/messages/{message_id}/feedback", dependencies=[Depends(require_origin)])
async def delete_feedback(message_id: UUID, user: dict = Depends(require_customer),
                          repository: AppDataRepository = Depends(repository_dependency)):
    await repository.delete_feedback(user["id"], str(message_id))
    return {"status": "deleted"}
