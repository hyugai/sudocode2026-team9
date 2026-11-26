"""Read-only cross-account history for the demo Salesman role."""
from collections.abc import AsyncIterator
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from telesale_agent.adapters.db.app_repository import AppDataNotFound
from telesale_agent.adapters.db.salesman_repository import SalesmanRepository
from .auth import auth_error, get_auth_repository, require_salesman
from .conversations import no_store


async def history_repository(app_repository=Depends(get_auth_repository)) -> AsyncIterator[SalesmanRepository]:
    try:
        yield SalesmanRepository(app_repository.engine)
    except AppDataNotFound as exc:
        raise auth_error(404, "Không tìm thấy hội thoại.") from exc
    except SQLAlchemyError as exc:
        raise auth_error(503, "Chưa kết nối được lịch sử. Hãy thử lại.") from exc


router = APIRouter(prefix="/api/salesman", tags=["salesman"],
                   dependencies=[Depends(require_salesman), Depends(no_store)])


@router.get("/conversations")
async def list_conversations(q: str = Query("", max_length=200), source: Literal["all", "chat", "voice"] = "all",
                             limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                             repository=Depends(history_repository)):
    return await repository.list(q, source, limit, offset)


@router.get("/conversations/{source}/{conversation_id}")
async def get_conversation(source: Literal["chat", "voice"], conversation_id: str,
                           limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                           repository=Depends(history_repository)):
    if not conversation_id or len(conversation_id) > 160:
        raise auth_error(422, "Mã hội thoại không hợp lệ.")
    if source == "chat":
        try:
            conversation_id = str(UUID(conversation_id))
        except ValueError as exc:
            raise auth_error(422, "Mã hội thoại Chat không hợp lệ.") from exc
    return await repository.get(source, conversation_id, limit, offset)
