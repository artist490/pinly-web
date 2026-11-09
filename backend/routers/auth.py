# Маршруты аккаунтов: /api/auth/* (вход, сессия, профиль, удаление).

import sqlite3

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from .. import accounts, erasure, ratelimit, session
from ..deps import current_user, session_payload
from ..schemas import DisplayNameBody, LoginBody, RegisterBody

router = APIRouter()


@router.post("/api/auth/register")
def auth_register(body: RegisterBody, request: Request, response: Response) -> dict:
    ratelimit.rate_limit(request, "auth")
    row = accounts.register(
        body.email, body.password, body.display_name, body.consent, request.headers.get("user-agent")
    )
    session.set_session_cookie(request, response, row["id"], row["email"], row["session_version"])
    return {"user": accounts.user_json(row)}


@router.post("/api/auth/login")
def auth_login(body: LoginBody, request: Request, response: Response) -> dict:
    """Неверная пара — 401, перебор — 429: оба статуса обязаны появляться,
    иначе лимит обходится бесконечными 401."""
    ratelimit.rate_limit(request, "auth")
    # второй счётчик — по адресу, а не по IP: за прокси у всех один адрес, и
    # общий бакет превращал перебор в блокировку входа для всех сразу
    ratelimit.rate_limit_key(f"auth-email:{body.email.strip().lower()}", 20, 300.0)
    row = accounts.login(body.email, body.password)
    session.set_session_cookie(request, response, row["id"], row["email"], row["session_version"])
    return {"user": accounts.user_json(row)}


@router.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    """Выход отзывает токен, а не только стирает куку: скопированная заранее
    кука перестаёт работать сразу, а не через 30 дней."""
    user_id = (session_payload(request) or {}).get("sub")
    if user_id and accounts.user_by_id(user_id) is not None:
        accounts.revoke_sessions(user_id)
    session.clear_session_cookie(response)
    return {"ok": True}


@router.get("/api/auth/me")
def auth_me(user: sqlite3.Row = Depends(current_user)) -> dict:
    return {"user": accounts.user_json(user)}


@router.patch("/api/auth/me")
def auth_update_me(
    body: DisplayNameBody, user: sqlite3.Row = Depends(current_user)
) -> dict:
    return {"user": accounts.user_json(accounts.rename_user(user["id"], body.display_name))}


@router.post("/api/auth/avatar")
async def auth_avatar(
    request: Request,
    file: UploadFile = File(...),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    ratelimit.rate_limit(request, "avatar", limit=10, window_s=3600.0)
    content = await file.read(accounts.MAX_AVATAR_BYTES + 1)
    return {"user": accounts.user_json(accounts.replace_avatar(user, content))}


@router.delete("/api/auth/account")
def auth_delete_account(
    response: Response, user: sqlite3.Row = Depends(current_user)
) -> dict:
    # 152-ФЗ: удаление аккаунта и персональных данных — строки, файлы и
    # векторы; каскад чужих таблиц собран в erasure.py.
    erasure.erase_account(user)
    session.clear_session_cookie(response)
    return {"ok": True}
