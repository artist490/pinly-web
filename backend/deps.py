# Зависимости FastAPI: кто делает запрос.
#
# Единственный способ достать текущую сессию из маршрутов. Раньше каждый
# эндпоинт вызывал _current_user_row(request) руками (~40 мест); здесь три
# варианта названы явно и различаются тем, что происходит без сессии:
#   session_payload — только подписанный токен (события, сводка владельца);
#   optional_user   — профиль, если вошёл, иначе None (публичные страницы);
#   current_user    — профиль или 401 "no session";
#   require_admin   — профиль владельца (PINLY_OWNER_EMAIL) или 403.
#
# Владельческие данные (сводка событий, панель модерации) закрыты fail-closed:
# нет PINLY_OWNER_EMAIL — доступ закрыт, а не открыт. Открыть его на локальном
# стенде можно только явным PINLY_ALLOW_LOCAL_ADMIN=1. Раньше «переменная не
# задана» означало «можно всем вошедшим», и одна забытая настройка на боевом
# сервере отдавала бан пользователей любому зарегистрированному.

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


def session_revoked(payload: dict, row: sqlite3.Row) -> bool:
    """Токен выпущен до отзыва сессий? В payload лежит версия на момент входа,
    в базе — текущая; выход и бан её поднимают.

    Отсутствие sv — токен старого формата, он соответствует версии 0: после
    деплоя уже выданные сессии продолжают работать, пока пользователь сам не
    выйдет.
    """
    return int(payload.get("sv", 0)) != int(row["session_version"] or 0)


def current_user(request: Request) -> sqlite3.Row:
    payload = session_payload(request) or {}
    row = user_by_id(payload.get("sub", ""))
    if row is None:
        raise HTTPException(401, "no session")
    # вышедший или забаненный пользователь: подпись ещё верна, но сессии уже нет
    if session_revoked(payload, row):
        raise HTTPException(401, "session revoked")
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
    if row is None or session_revoked(payload, row) or row["is_blocked"]:
        return None
    return row


def owner_email() -> str:
    return os.environ.get("PINLY_OWNER_EMAIL", "").strip().lower()


def local_admin_allowed() -> bool:
    """Локальный стенд и тесты: панель открыта без владельца, но только по
    явному флагу и никогда в проде. Отказ конфигурации обязан закрывать
    доступ, а не открывать."""
    production = os.environ.get("PINLY_ENV", "").strip().lower() == "production"
    return os.environ.get("PINLY_ALLOW_LOCAL_ADMIN") == "1" and not production


def is_admin_email(email: str | None) -> bool:
    """Админ — владелец сайта по email из окружения (тот же ключ, что читает
    events.summary). Флаг отвечает на вопрос «показывать ли ссылку на панель»,
    поэтому локальный обход PINLY_ALLOW_LOCAL_ADMIN его не включает: на стенде
    панель открыта по прямому адресу, а чужим «я админ» фронт не говорит."""
    owner = owner_email()
    return bool(owner) and bool(email) and email.strip().lower() == owner


def require_owner(payload: dict | None, what: str = "moderation") -> dict:
    """Общий гейт владельческих данных: сводка событий и панель модерации.

    Порядок проверок — часть контракта: без сессии 401, не владелец 403,
    владелец не настроен 404 (эндпоинт как бы не существует).
    """
    if not payload or "sub" not in payload:
        raise HTTPException(401, "login required")
    owner = owner_email()
    if not owner and not local_admin_allowed():
        raise HTTPException(404, f"{what} disabled")
    if owner and str(payload.get("email", "")).lower() != owner:
        raise HTTPException(403, "not owner")
    return payload


def require_admin(request: Request) -> sqlite3.Row:
    """Панель модерации: профиль владельца сайта или 403/404."""
    payload = require_owner(session_payload(request), "moderation")
    row = user_by_id(payload["sub"])
    if row is None:
        raise HTTPException(401, "no session")
    return row
