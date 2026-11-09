"""Email/password auth backed by the application tables (no agent dependency)."""

import asyncio
import hashlib
import json
import os
import re
import secrets
from datetime import timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from telesale_agent.adapters.db.app_models import utc_now
from telesale_agent.adapters.db.app_repository import AppDataRepository
from telesale_agent.adapters.db.app_schema import create_app_engine

COOKIE_NAME = "synee_session"
NO_STORE = {"Cache-Control": "no-store"}
passwords = PasswordHash.recommended()
dummy_hash = passwords.hash("not-a-user-password-" + secrets.token_urlsafe(32))
router = APIRouter(prefix="/api/auth", tags=["auth"])


def auth_error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message, headers=NO_STORE)


@lru_cache
def get_auth_repository() -> AppDataRepository:
    try:
        return AppDataRepository(create_app_engine())
    except (ValueError, SQLAlchemyError) as exc:
        raise auth_error(503, "Chưa kết nối được dịch vụ tài khoản.") from exc


def require_origin(request: Request) -> None:
    origin = os.environ.get("WEB_ORIGIN", "http://localhost:3000").rstrip("/")
    if request.headers.get("origin") != origin:
        raise auth_error(403, "Nguồn gửi yêu cầu không được phép.")


def cookie_secure() -> bool:
    configured = os.environ.get("SESSION_COOKIE_SECURE")
    if configured is not None:
        return configured.lower() == "true"
    return os.environ.get("WEB_ORIGIN", "http://localhost:3000").startswith("https://")


def session_token(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME, "")
    return token if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) else None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def credentials(request: Request, *, register: bool = False) -> dict[str, str]:
    # Validate explicitly so errors never echo passwords in FastAPI's input field.
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise auth_error(415, "Gửi thông tin tài khoản ở định dạng JSON.")
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise auth_error(422, "Thông tin tài khoản không hợp lệ.") from exc
    expected = {"email", "password", "name"} if register else {"email", "password"}
    if not isinstance(body, dict) or set(body) != expected or any(not isinstance(value, str) for value in body.values()):
        raise auth_error(422, "Thông tin tài khoản không hợp lệ.")
    email = body["email"].strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise auth_error(422, "Nhập địa chỉ email hợp lệ.")
    if not (8 if register else 1) <= len(body["password"]) <= 128:
        raise auth_error(422, "Mật khẩu phải có từ 8–128 ký tự." if register else "Nhập mật khẩu hợp lệ.")
    if register and not 2 <= len(body["name"].strip()) <= 100:
        raise auth_error(422, "Nhập họ và tên từ 2–100 ký tự.")
    return {**body, "email": email}


async def require_user(request: Request, repository: AppDataRepository = Depends(get_auth_repository)) -> dict:
    if request.headers.get("origin") is not None:
        require_origin(request)
    token = session_token(request)
    if token is None:
        raise auth_error(401, "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
    try:
        user = await repository.get_session_user(token_hash(token))
    except SQLAlchemyError as exc:
        raise auth_error(503, "Chưa kết nối được dịch vụ tài khoản.") from exc
    if user is None:
        raise auth_error(401, "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
    return user


@router.post("/register", status_code=201, dependencies=[Depends(require_origin)])
async def register(request: Request, response: Response,
                   repository: AppDataRepository = Depends(get_auth_repository)):
    body = await credentials(request, register=True)
    hashed = await asyncio.to_thread(passwords.hash, body["password"])
    try:
        user = await repository.create_user(body["name"], body["email"], hashed)
    except IntegrityError as exc:
        raise auth_error(409, "Email này đã được đăng ký. Hãy đăng nhập.") from exc
    except SQLAlchemyError as exc:
        raise auth_error(503, "Chưa lưu được tài khoản. Vui lòng thử lại.") from exc
    response.headers.update(NO_STORE)
    return {"user": user}


@router.post("/login", dependencies=[Depends(require_origin)])
async def login(request: Request, response: Response,
                repository: AppDataRepository = Depends(get_auth_repository)):
    body = await credentials(request)
    try:
        ttl = timedelta(days=int(os.environ.get("SESSION_TTL_DAYS", "7")))
        if ttl.total_seconds() <= 0:
            raise ValueError("SESSION_TTL_DAYS must be positive")
    except (ValueError, OverflowError) as exc:
        raise auth_error(503, "Cấu hình thời hạn đăng nhập chưa hợp lệ.") from exc
    try:
        user = await repository.find_user_credentials(body["email"])
        valid = await asyncio.to_thread(passwords.verify, body["password"], user["password_hash"] if user else dummy_hash)
        if not valid or user is None:
            raise auth_error(401, "Email hoặc mật khẩu chưa đúng.")
        previous = session_token(request)
        if previous:
            await repository.delete_auth_session(token_hash(previous))
        token = secrets.token_urlsafe(32)
        expires = utc_now() + ttl
        await repository.create_auth_session(user["id"], token_hash(token), expires)
    except SQLAlchemyError as exc:
        raise auth_error(503, "Chưa tạo được phiên đăng nhập. Vui lòng thử lại.") from exc
    response.set_cookie(COOKIE_NAME, token, max_age=int(ttl.total_seconds()), expires=expires,
                        httponly=True, secure=cookie_secure(), samesite="lax", path="/")
    response.headers.update(NO_STORE)
    return {"user": {key: user[key] for key in ("id", "name", "email")}}


@router.get("/me")
async def me(response: Response, user: dict = Depends(require_user)):
    response.headers.update(NO_STORE)
    return {"user": user}


@router.post("/logout", dependencies=[Depends(require_origin)])
async def logout(request: Request, response: Response,
                 repository: AppDataRepository = Depends(get_auth_repository)):
    token = session_token(request)
    try:
        if token:
            await repository.delete_auth_session(token_hash(token))
    except SQLAlchemyError as exc:
        raise auth_error(503, "Chưa đăng xuất được. Vui lòng thử lại.") from exc
    response.delete_cookie(COOKIE_NAME, httponly=True, secure=cookie_secure(), samesite="lax", path="/")
    response.headers.update(NO_STORE)
    return {"status": "logged_out"}
