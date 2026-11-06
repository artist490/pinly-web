# Группы по общим тематикам: таблицы communities, group_members, group_pins.
#
# Группа — сообщество вокруг тематики: свободное вступление, лента пинов из
# снапшотов (тот же каркас, что у досок и чатов — schemas.pin_card_json),
# публикуют владелец и те, кому он выдал право (role = 'poster').
#
# Таблица названа communities, а не groups: GROUPS — зарезервированное слово
# SQLite (кадры оконных функций), и не стоит проверять на живой базе, где
# именно парсер собьётся.
#
# Функции без conn открывают своё соединение (их зовёт слой маршрутов),
# функции с conn работают внутри уже начатой транзакции — так их зовут
# соседи по домену и erasure.py.

import json
import sqlite3
import time
import uuid

from fastapi import HTTPException

from . import accounts
from .db import connection

GROUP_PREVIEW_PINS = 60
MAX_TITLE_LEN = 80
MAX_DESC_LEN = 500
ROLES = ("owner", "poster", "member")


def group_title(raw: str) -> str:
    return raw.strip()[:MAX_TITLE_LEN]


def clean_description(raw: str) -> str:
    return (raw or "").strip()[:MAX_DESC_LEN]


def clean_category(raw: str) -> str:
    return (raw or "").strip()[:60]


def _require_group(conn: sqlite3.Connection, group_id: str) -> sqlite3.Row:
    group = conn.execute("select * from communities where id = ?", (group_id,)).fetchone()
    if group is None or group["is_hidden"]:
        raise HTTPException(404, "group not found")
    return group


def role_of(conn: sqlite3.Connection, group_id: str, user_id: str | None) -> str | None:
    if not user_id:
        return None
    row = conn.execute(
        "select role from group_members where group_id = ? and user_id = ?",
        (group_id, user_id),
    ).fetchone()
    return row["role"] if row else None


def _can_post(role: str | None) -> bool:
    return role in ("owner", "poster")


def group_json(conn: sqlite3.Connection, group: sqlite3.Row) -> dict:
    """Карточка группы для списков: без ленты пинов, с числами."""
    members_count = conn.execute(
        "select count(*) as c from group_members where group_id = ?", (group["id"],)
    ).fetchone()["c"]
    pins_count = conn.execute(
        "select count(*) as c from group_pins where group_id = ?", (group["id"],)
    ).fetchone()["c"]
    owner = accounts.user_row(conn, group["owner_id"])
    return {
        "id": group["id"],
        "title": group["title"],
        "description": group["description"],
        "category": group["category"],
        "createdAt": int(group["created_at"] * 1000),
        "membersCount": members_count,
        "pinsCount": pins_count,
        "owner": {
            "id": group["owner_id"],
            "name": (owner["display_name"] if owner else None) or "Пользователь",
        },
    }


def group_feed(conn: sqlite3.Connection, group_id: str) -> list[dict]:
    rows = conn.execute(
        "select pin_data from group_pins where group_id = ? order by added_at desc limit ?",
        (group_id, GROUP_PREVIEW_PINS),
    ).fetchall()
    return [json.loads(r["pin_data"]) for r in rows]


def create(me_id: str, title_raw: str, description: str, category: str) -> dict:
    title = group_title(title_raw)
    if not title:
        raise HTTPException(400, "title required")
    group_id = str(uuid.uuid4())
    with connection() as conn:
        conn.execute(
            "insert into communities (id, owner_id, title, description, category, created_at) "
            "values (?, ?, ?, ?, ?, ?)",
            (group_id, me_id, title, clean_description(description), clean_category(category), time.time()),
        )
        conn.execute(
            "insert into group_members (group_id, user_id, role, joined_at) values (?, ?, 'owner', ?)",
            (group_id, me_id, time.time()),
        )
        group = conn.execute("select * from communities where id = ?", (group_id,)).fetchone()
        return group_json(conn, group)


def update(me_id: str, group_id: str, title: str, description: str, category: str) -> dict:
    with connection() as conn:
        group = _require_group(conn, group_id)
        if group["owner_id"] != me_id:
            raise HTTPException(403, "not owner")
        conn.execute(
            "update communities set title = ?, description = ?, category = ? where id = ?",
            (
                group_title(title) or group["title"],
                clean_description(description),
                clean_category(category),
                group_id,
            ),
        )
        fresh = conn.execute("select * from communities where id = ?", (group_id,)).fetchone()
        return group_json(conn, fresh)


def delete(me_id: str, group_id: str) -> None:
    """Члены и пины уходят по каскаду FK communities(id)."""
    with connection() as conn:
        group = _require_group(conn, group_id)
        if group["owner_id"] != me_id:
            raise HTTPException(403, "not owner")
        conn.execute("delete from communities where id = ?", (group_id,))


def list_mine(me_id: str) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            "select c.* from communities c join group_members m on m.group_id = c.id "
            "where m.user_id = ? order by c.created_at desc",
            (me_id,),
        ).fetchall()
        return [{**group_json(conn, g), "myRole": role_of(conn, g["id"], me_id)} for g in rows]


def list_public(category: str | None, q: str | None, limit: int = 40) -> list[dict]:
    """Публичный каталог: фильтр по категории в SQL, подстрока — в Python:
    SQL-ный lower() знает только ASCII, а названия групп кириллические."""
    where = ["(is_hidden = 0 or is_hidden is null)"]
    args: list = []
    if category:
        where.append("category = ?")
        args.append(clean_category(category))
    wanted = (q or "").strip().lower()
    with connection() as conn:
        rows = conn.execute(
            f"select * from communities where {' and '.join(where)} "
            "order by created_at desc limit ?",
            [*args, max(1, min(limit, 100)) * (5 if wanted else 1)],
        ).fetchall()
        found = [
            row
            for row in rows
            if not wanted
            or wanted in row["title"].lower()
            or wanted in (row["description"] or "").lower()
        ]
        return [group_json(conn, g) for g in found[: max(1, min(limit, 100))]]


def public_group(group_id: str, viewer_id: str | None = None) -> dict:
    with connection() as conn:
        group = _require_group(conn, group_id)
        data = group_json(conn, group)
        data["pins"] = group_feed(conn, group_id)
        data["myRole"] = role_of(conn, group_id, viewer_id)
        return data


def members(group_id: str, viewer_id: str | None = None) -> list[dict]:
    with connection() as conn:
        group = _require_group(conn, group_id)
        rows = conn.execute(
            "select m.role, m.joined_at, u.id, u.display_name, u.avatar_url "
            "from group_members m join users u on u.id = m.user_id "
            "where m.group_id = ? order by m.joined_at asc limit 200",
            (group_id,),
        ).fetchall()
        can_manage = bool(viewer_id) and viewer_id == group["owner_id"]
        return [
            {
                "id": r["id"],
                "name": r["display_name"] or "Пользователь",
                "avatarUrl": r["avatar_url"],
                "role": r["role"],
                "joinedAt": int(r["joined_at"] * 1000),
                "canManage": can_manage,
            }
            for r in rows
        ]


def join(me_id: str, group_id: str) -> None:
    with connection() as conn:
        _require_group(conn, group_id)
        conn.execute(
            "insert or ignore into group_members (group_id, user_id, role, joined_at) "
            "values (?, ?, 'member', ?)",
            (group_id, me_id, time.time()),
        )


def leave(me_id: str, group_id: str) -> None:
    with connection() as conn:
        group = _require_group(conn, group_id)
        if group["owner_id"] == me_id:
            raise HTTPException(400, "owner cannot leave")
        conn.execute(
            "delete from group_members where group_id = ? and user_id = ?", (group_id, me_id)
        )


def add_pin(me_id: str, group_id: str, pin_id: str, card: str) -> None:
    with connection() as conn:
        _require_group(conn, group_id)
        if not _can_post(role_of(conn, group_id, me_id)):
            raise HTTPException(403, "posting not allowed")
        conn.execute(
            "insert into group_pins (group_id, pin_id, pin_data, added_by, added_at) "
            "values (?, ?, ?, ?, ?) "
            "on conflict (group_id, pin_id) do update set pin_data = excluded.pin_data",
            (group_id, pin_id, card, me_id, time.time()),
        )


def remove_pin(me_id: str, group_id: str, pin_id: str) -> None:
    with connection() as conn:
        group = _require_group(conn, group_id)
        row = conn.execute(
            "select added_by from group_pins where group_id = ? and pin_id = ?",
            (group_id, pin_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "pin not found in group")
        if row["added_by"] != me_id and group["owner_id"] != me_id:
            raise HTTPException(403, "not allowed")
        conn.execute(
            "delete from group_pins where group_id = ? and pin_id = ?", (group_id, pin_id)
        )


def set_role(me_id: str, group_id: str, user_id: str, role: str) -> dict:
    """Владелец выдаёт или снимает право публикации. Роль 'owner' так не
    выдаётся: владелец у группы один, передача — отдельное решение."""
    if role not in ("poster", "member"):
        raise HTTPException(400, "unknown role")
    with connection() as conn:
        group = _require_group(conn, group_id)
        if group["owner_id"] != me_id:
            raise HTTPException(403, "not owner")
        if user_id == me_id:
            raise HTTPException(400, "cannot change own role")
        if role_of(conn, group_id, user_id) is None:
            raise HTTPException(404, "not a member")
        conn.execute(
            "update group_members set role = ? where group_id = ? and user_id = ?",
            (role, group_id, user_id),
        )
        return {"ok": True, "role": role}


def postable_groups(me_id: str) -> list[dict]:
    """Группы, где человек может публиковать (для меню «добавить в группу»)."""
    with connection() as conn:
        rows = conn.execute(
            "select c.id, c.title, m.role from communities c "
            "join group_members m on m.group_id = c.id "
            "where m.user_id = ? and m.role in ('owner', 'poster') "
            "and (c.is_hidden = 0 or c.is_hidden is null) order by c.created_at desc",
            (me_id,),
        ).fetchall()
        return [{"id": r["id"], "title": r["title"], "role": r["role"]} for r in rows]


# --- чистка (вызывается из erasure.py) ---


def remove_rows_of_user_pins(conn: sqlite3.Connection, user_id: str) -> None:
    """Снапшоты своих пинов в чужих группах: group_pins.pin_id без FK на pins."""
    conn.execute(
        "delete from group_pins where pin_id in (select id from pins where user_id = ?)",
        (user_id,),
    )
