# Зависимости FastAPI: кто делает запрос.
#
# Единственный способ достать текущую сессию из маршрутов. Раньше каждый
# эндпоинт вызывал _current_user_row(request) руками (~40 мест); здесь три
# варианта названы явно и различаются тем, что происходит без сессии:
#   session_payload — только подписанный токен (события, сводка владельца);
#   optional_user   — профиль, если вошёл, иначе None (публичные страницы);
#   current_user    — профиль или 401 "no session";
#   require_admin   — профиль владельца (PINLY_OWNER_EMAIL) или 403.

import os
import sqlite3

from fastapi import HTTPException, Request

from .accounts import user_by_id
from .session import SESSION_COOKIE, jwt_decode


def session_payload(request: Request) -> dict | None:
    """Разобрать куку сессии: подпись и срок действия проверены, пользователя
    в базе может уже и не быть."""
    token = request.cookies.get(SESSION_COOKIE, "")
    return jwt_decode(token) if token else None


def current_user(request: Request) -> sqlite3.Row:
    row = user_by_id((session_payload(request) or {}).get("sub", ""))
    if row is None:
        raise HTTPException(401, "no session")
    # заблокированный модератором аккаунт теряет и сессию: токен ещё жив,
    # но вход по нему больше ничего не открывает
    if row["is_blocked"]:
        raise HTTPException(401, "account blocked")
    return row


def optional_user(request: Request) -> sqlite3.Row | None:
    payload = session_payload(request)
    if not payload or "sub" not in payload:
        return None
    row = user_by_id(payload["sub"])
    if row is not None and row["is_blocked"]:
        return None
    return row


def is_admin_email(email: str | None) -> bool:
    """Админ — владелец сайта по email из окружения (тот же ключ, что читает
    events.summary)."""
    owner = os.environ.get("PINLY_OWNER_EMAIL", "").strip().lower()
    return bool(owner) and bool(email) and email.strip().lower() == owner


def require_admin(request: Request) -> sqlite3.Row:
    """Панель модерации: та же семантика, что у events.summary — в проде
    только владелец (PINLY_OWNER_EMAIL), локально без настроек панель не
    заперта, иначе смоук не написать без внешнего конфига."""
    payload = session_payload(request)
    if not payload or "sub" not in payload:
        raise HTTPException(401, "login required")
    owner = os.environ.get("PINLY_OWNER_EMAIL", "").strip().lower()
    production = os.environ.get("PINLY_ENV", "").strip().lower() == "production"
    if owner and str(payload.get("email", "")).lower() != owner:
        raise HTTPException(403, "not owner")
    if production and not owner:
        raise HTTPException(404, "moderation disabled")
    row = user_by_id(payload["sub"])
    if row is None:
        raise HTTPException(401, "no session")
    return row
