# Модерация: таблица reports — жалобы вошедших пользователей, решения по ним
# и флаги скрытия (pins.is_hidden, users.is_blocked).
#
# Жалоба — не событие из events.py, а объект со статусом: у неё есть автор,
# цель и вердикт. Событие report для анонимов остаётся как было — это счётчик,
# а не очередь.
#
# Скрытие мягкое: пин перестаёт существовать для всех выборок, но строка и
# файлы остаются — решение обратимо, в отличие от erase_pin. Бан работает так
# же: аккаунт не входит, сессия не признаётся, но данные на месте (152-ФЗ
# стирание — отдельная процедура по запросу пользователя, не модератора).

import sqlite3
import time
import uuid

from fastapi import HTTPException

from . import pins
from .db import connection

TARGET_TYPES = ("pin", "board", "user", "group")
REASONS = ("spam", "copyright", "offensive")
REPORTS_PAGE = 100


def create_report(me_id: str, target_type: str, target_id: str, reason: str) -> str:
    if target_type not in TARGET_TYPES:
        raise HTTPException(400, "unknown target")
    if reason not in REASONS:
        raise HTTPException(400, "unknown reason")
    if not target_id or len(target_id) > 128:
        raise HTTPException(400, "invalid target_id")
    report_id = str(uuid.uuid4())
    with connection() as conn:
        # дедуп: один открытый отчёт от человека на цель — повторный клик
        # по «Пожаловаться» не плодит очередь из одинаковых строк
        dup = conn.execute(
            "select 1 from reports where reporter_id = ? and target_type = ? "
            "and target_id = ? and status = 'open'",
            (me_id, target_type, target_id),
        ).fetchone()
        if dup is not None:
            raise HTTPException(409, "already reported")
        conn.execute(
            "insert into reports (id, reporter_id, target_type, target_id, reason, created_at) "
            "values (?, ?, ?, ?, ?, ?)",
            (report_id, me_id, target_type, target_id, reason, time.time()),
        )
    return report_id


def open_reports(limit: int = REPORTS_PAGE) -> list[dict]:
    """Очередь открытых жалоб: кто, на что и за что. Идентичность жалобщика
    панели не нужна — решение принимается по цели и причине."""
    with connection() as conn:
        rows = conn.execute(
            "select * from reports where status = 'open' order by created_at desc limit ?",
            (limit,),
        ).fetchall()
        return [report_json(conn, row) for row in rows]


def report_json(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    target: dict = {}
    if row["target_type"] == "pin":
        pin_row = pins.row_by_id(conn, row["target_id"])
        target = {
            "title": pin_row["title"] if pin_row else None,
            "exists": pin_row is not None,
            "hidden": bool(pin_row["is_hidden"]) if pin_row else False,
        }
    elif row["target_type"] == "user":
        user = conn.execute(
            "select display_name, is_blocked from users where id = ?", (row["target_id"],)
        ).fetchone()
        target = {
            "title": (user["display_name"] if user else None) or "Пользователь",
            "exists": user is not None,
            "hidden": bool(user["is_blocked"]) if user else False,
        }
    elif row["target_type"] == "group":
        group = conn.execute(
            "select title, is_hidden from communities where id = ?", (row["target_id"],)
        ).fetchone()
        target = {
            "title": group["title"] if group else None,
            "exists": group is not None,
            "hidden": bool(group["is_hidden"]) if group else False,
        }
    else:  # board
        board = conn.execute(
            "select title from boards where id = ?", (row["target_id"],)
        ).fetchone()
        target = {"title": board["title"] if board else None, "exists": board is not None}
    return {
        "id": row["id"],
        "targetType": row["target_type"],
        "targetId": row["target_id"],
        "reason": row["reason"],
        "createdAt": int(row["created_at"] * 1000),
        "target": target,
    }


def resolve_report(me_id: str, report_id: str, action: str) -> dict:
    """Вердикт: hide_pin — скрыть пин, ban_user — заблокировать владельца
    цели (для жалобы на пользователя — самого), dismiss — отклонить."""
    actions = {"dismiss", "hide_pin", "ban_user"}
    if action not in actions:
        raise HTTPException(400, "unknown action")
    with connection() as conn:
        report = conn.execute("select * from reports where id = ?", (report_id,)).fetchone()
        if report is None:
            raise HTTPException(404, "report not found")
        # вердикт выносится один раз: повтор по уже решённой жалобе — гонка
        # двух админов, а не новое решение
        if report["status"] != "open":
            raise HTTPException(409, "already resolved")
        if action == "hide_pin":
            if report["target_type"] != "pin":
                raise HTTPException(400, "not a pin report")
            conn.execute("update pins set is_hidden = 1 where id = ?", (report["target_id"],))
        elif action == "ban_user":
            banned = _user_to_ban(conn, report)
            if banned is None:
                raise HTTPException(404, "target user not found")
            if banned == me_id:
                raise HTTPException(400, "cannot ban yourself")
            # бан поднимает и поколение сессий: is_blocked закрывает доступ
            # сразу, а session_version не даёт вернуться, даже если флаг
            # is_blocked когда-нибудь снимут вручную
            conn.execute(
                "update users set is_blocked = 1, session_version = session_version + 1"
                " where id = ?",
                (banned,),
            )
        conn.execute("update reports set status = 'resolved' where id = ?", (report_id,))
        return {"ok": True}


def _user_to_ban(conn: sqlite3.Connection, report: sqlite3.Row) -> str | None:
    """Кого банить по жалобе: владельца пина, владельца доски или самого
    пользователя. Внешние пины (ov-…) владельца не имеют — банить некого."""
    target_id = report["target_id"]
    if report["target_type"] == "user":
        return target_id
    if report["target_type"] == "pin":
        return pins.owner_id_of(conn, target_id)
    if report["target_type"] == "group":
        row = conn.execute(
            "select owner_id from communities where id = ?", (target_id,)
        ).fetchone()
        return row["owner_id"] if row else None
    row = conn.execute("select user_id from boards where id = ?", (target_id,)).fetchone()
    return row["user_id"] if row else None


# --- чистка (вызывается из erasure.py) ---


def remove_user_rows(conn: sqlite3.Connection, user_id: str) -> None:
    """Свои жалобы уходят с аккаунтом; жалобы на стёртые цели остаются —
    по ним видно, что цель удалили сами."""
    conn.execute("delete from reports where reporter_id = ?", (user_id,))
