# Соцблок: подписки, комментарии и публичные профили (таблицы follows, comments).
#
# Email пользователей наружу не отдаётся никогда — только имя и аватар.
# Секретные доски (boards.is_secret) не видны никому, кроме владельца: для
# чужих их не существует, а не «доступ запрещён».

import sqlite3
import time
import uuid

from fastapi import HTTPException

from . import boards, pins
from .db import connection

MAX_COMMENT_LEN = 1000
COMMENTS_PAGE = 200
SUBSCRIPTIONS_PINS = 40
SUBSCRIPTIONS_BOARDS = 20


def require_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row:
    row = conn.execute("select * from users where id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "user not found")
    return row


def profile_json(conn: sqlite3.Connection, row: sqlite3.Row, viewer_id: str | None) -> dict:
    """Публичная карточка профиля: цифры и имя, никаких персональных полей."""
    return {
        "id": row["id"],
        # e-mail наружу не отдаём никогда — только имя, которое человек
        # ввёл сам (или «Пользователь», если имени нет)
        "displayName": row["display_name"] or "Пользователь",
        "avatarUrl": row["avatar_url"] if "avatar_url" in row.keys() else None,
        "pinsCount": conn.execute(
            "select count(*) as c from pins where user_id = ?", (row["id"],)
        ).fetchone()["c"],
        "boardsCount": boards.count_public(conn, row["id"]),
        "followers": followers_count(conn, row["id"]),
        "following": following_count(conn, row["id"]),
        "isFollowing": is_following(conn, viewer_id, row["id"]),
        "isSelf": viewer_id == row["id"],
        "createdAt": int(row["created_at"] * 1000),
    }


def profile(user_id: str, viewer_id: str | None) -> dict:
    with connection() as conn:
        return profile_json(conn, require_user(conn, user_id), viewer_id)


def user_pins(user_id: str, limit: int | None = None) -> list[dict]:
    with connection() as conn:
        require_user(conn, user_id)
        return pins.cards(conn, pins.pins_of_user(conn, user_id, limit))


def user_boards(user_id: str) -> list[dict]:
    with connection() as conn:
        require_user(conn, user_id)
        return boards.list_public(conn, user_id)


# --- подписки ---


def followers_count(conn: sqlite3.Connection, user_id: str) -> int:
    return conn.execute(
        "select count(*) as c from follows where followee_id = ?", (user_id,)
    ).fetchone()["c"]


def following_count(conn: sqlite3.Connection, user_id: str) -> int:
    return conn.execute(
        "select count(*) as c from follows where follower_id = ?", (user_id,)
    ).fetchone()["c"]


def is_following(conn: sqlite3.Connection, viewer_id: str | None, user_id: str) -> bool:
    if not viewer_id:
        return False
    return (
        conn.execute(
            "select 1 from follows where follower_id = ? and followee_id = ?",
            (viewer_id, user_id),
        ).fetchone()
        is not None
    )


def follow(me_id: str, user_id: str) -> None:
    with connection() as conn:
        if me_id == user_id:
            raise HTTPException(400, "cannot follow yourself")
        require_user(conn, user_id)
        conn.execute(
            "insert or ignore into follows (follower_id, followee_id, created_at) values (?, ?, ?)",
            (me_id, user_id, time.time()),
        )


def unfollow(me_id: str, user_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "delete from follows where follower_id = ? and followee_id = ?", (me_id, user_id)
        )


def subscriptions_feed(me_id: str) -> dict:
    """Загрузки пользователей, на которых подписан + их публичные доски."""
    with connection() as conn:
        ids = [
            r["followee_id"]
            for r in conn.execute(
                "select followee_id from follows where follower_id = ?", (me_id,)
            ).fetchall()
        ]
        if not ids:
            return {"pins": [], "boards": []}
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"select * from pins where user_id in ({placeholders}) "
            "order by created_at desc limit ?",
            [*ids, SUBSCRIPTIONS_PINS],
        ).fetchall()
        return {
            "pins": pins.cards(conn, rows),
            "boards": boards.recent_public_boards(conn, ids, SUBSCRIPTIONS_BOARDS),
        }


# --- комментарии ---

# Ответы — один уровень: отвечать можно только комментарию верхнего уровня,
# и все ответы лежат плоско под ним (так делает Пинтерест; ветки любой
# глубины на телефоне съедают ширину и не читаются).


def _comment_json(r: sqlite3.Row, likes: int, liked_by_me: bool) -> dict:
    return {
        "id": r["id"],
        "text": r["text"],
        "createdAt": int(r["created_at"] * 1000),
        "likes": likes,
        "likedByMe": liked_by_me,
        "author": {
            "id": r["user_id"],
            "name": r["display_name"] or "Пользователь",
            "avatarUrl": r["avatar_url"],
        },
    }


def _like_stats(conn: sqlite3.Connection, comment_ids: list[str], viewer_id: str | None) -> dict:
    """Счётчики лайков одним запросом + факт «лайкнул ли зритель»."""
    if not comment_ids:
        return {}
    placeholders = ",".join("?" * len(comment_ids))
    counts = {
        row["comment_id"]: row["c"]
        for row in conn.execute(
            f"select comment_id, count(*) as c from comment_likes "
            f"where comment_id in ({placeholders}) group by comment_id",
            comment_ids,
        ).fetchall()
    }
    mine: set[str] = set()
    if viewer_id:
        mine = {
            row["comment_id"]
            for row in conn.execute(
                f"select comment_id from comment_likes where user_id = ? "
                f"and comment_id in ({placeholders})",
                [viewer_id, *comment_ids],
            ).fetchall()
        }
    return {cid: {"likes": counts.get(cid, 0), "likedByMe": cid in mine} for cid in comment_ids}


def list_comments(pin_id: str, viewer_id: str | None = None) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            "select c.*, u.display_name, u.avatar_url from comments c "
            "join users u on u.id = c.user_id where c.pin_id = ? "
            "order by c.created_at asc limit ?",
            (pin_id, COMMENTS_PAGE),
        ).fetchall()
        stats = _like_stats(conn, [r["id"] for r in rows], viewer_id)
        top: list[dict] = []
        by_parent: dict[str, list[dict]] = {}
        for r in rows:
            s = stats.get(r["id"], {"likes": 0, "likedByMe": False})
            item = _comment_json(r, s["likes"], s["likedByMe"])
            if r["parent_id"]:
                by_parent.setdefault(r["parent_id"], []).append(item)
            else:
                item["replies"] = []
                top.append(item)
        for item in top:
            item["replies"] = by_parent.get(item["id"], [])
        return top


def _require_comment(conn: sqlite3.Connection, comment_id: str) -> sqlite3.Row:
    row = conn.execute("select * from comments where id = ?", (comment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "comment not found")
    return row


def parent_author_id(comment_id: str) -> str | None:
    """Автор родительского комментария — адресат уведомления об ответе."""
    with connection() as conn:
        row = conn.execute(
            "select user_id from comments where id = ?", (comment_id,)
        ).fetchone()
        return row["user_id"] if row else None


def add_comment(me_id: str, pin_id: str, raw_text: str, parent_id: str | None = None) -> str:
    text = raw_text.strip()[:MAX_COMMENT_LEN]
    if not text:
        raise HTTPException(400, "empty comment")
    comment_id = str(uuid.uuid4())
    with connection() as conn:
        if parent_id:
            parent = _require_comment(conn, parent_id)
            # ответ только в тот же пин и только на комментарий верхнего уровня
            if parent["pin_id"] != pin_id or parent["parent_id"]:
                raise HTTPException(400, "invalid parent")
        conn.execute(
            "insert into comments (id, pin_id, user_id, parent_id, text, created_at) "
            "values (?, ?, ?, ?, ?, ?)",
            (comment_id, pin_id, me_id, parent_id, text, time.time()),
        )
    return comment_id


def delete_comment(me_id: str, comment_id: str) -> None:
    with connection() as conn:
        row = conn.execute("select * from comments where id = ?", (comment_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        # автор комментария или владелец пина
        if row["user_id"] != me_id and pins.owner_id_of(conn, row["pin_id"]) != me_id:
            raise HTTPException(403, "not allowed")
        # ответы без FK на родителя — чистятся руками, как и лайки
        conn.execute(
            "delete from comment_likes where comment_id in "
            "(select id from comments where parent_id = ? or id = ?)",
            (comment_id, comment_id),
        )
        conn.execute("delete from comments where parent_id = ? or id = ?", (comment_id, comment_id))


def like_comment(me_id: str, comment_id: str) -> int:
    """Лайк комментария; возвращает новый счётчик. Комментарий должен жить
    на существующем пине — комментарии мёртвых пинов не лайкаются."""
    with connection() as conn:
        comment = _require_comment(conn, comment_id)
        if pins.owner_id_of(conn, comment["pin_id"]) is None:
            raise HTTPException(404, "comment not found")
        conn.execute(
            "insert or ignore into comment_likes (user_id, comment_id, created_at) "
            "values (?, ?, ?)",
            (me_id, comment_id, time.time()),
        )
        return conn.execute(
            "select count(*) as c from comment_likes where comment_id = ?", (comment_id,)
        ).fetchone()["c"]


def unlike_comment(me_id: str, comment_id: str) -> int:
    with connection() as conn:
        conn.execute(
            "delete from comment_likes where user_id = ? and comment_id = ?", (me_id, comment_id)
        )
        return conn.execute(
            "select count(*) as c from comment_likes where comment_id = ?", (comment_id,)
        ).fetchone()["c"]


# --- чистка (вызывается из erasure.py) ---


def remove_pin_rows(conn: sqlite3.Connection, pin_id: str) -> None:
    """Комментарии ссылаются на pin_id без FK — иначе они пережили бы пин."""
    conn.execute(
        "delete from comment_likes where comment_id in "
        "(select id from comments where pin_id = ?)",
        (pin_id,),
    )
    conn.execute("delete from comments where pin_id = ?", (pin_id,))


def remove_user_rows(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute("delete from comment_likes where user_id = ?", (user_id,))
    # ответы чужих людей на комментарии этого пользователя: parent_id без FK,
    # без этой строки они пережили бы родителя и выпадали бы из выдачи
    conn.execute(
        "delete from comment_likes where comment_id in "
        "(select id from comments where parent_id in "
        "(select id from comments where user_id = ?))",
        (user_id,),
    )
    conn.execute(
        "delete from comments where parent_id in (select id from comments where user_id = ?)",
        (user_id,),
    )
    conn.execute("delete from comments where user_id = ?", (user_id,))


def remove_replies_to_user_comments(conn: sqlite3.Connection, user_id: str) -> None:
    """Хук для erase_account: комментарии самого пользователя уходят по каскаду
    FK (user_id references users), но ответы чужих людей на них — нет."""
    conn.execute(
        "delete from comment_likes where comment_id in "
        "(select id from comments where parent_id in "
        "(select id from comments where user_id = ?))",
        (user_id,),
    )
    conn.execute(
        "delete from comments where parent_id in (select id from comments where user_id = ?)",
        (user_id,),
    )


def remove_rows_of_user_pins(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute(
        "delete from comment_likes where comment_id in "
        "(select id from comments where pin_id in (select id from pins where user_id = ?))",
        (user_id,),
    )
    conn.execute(
        "delete from comments where pin_id in (select id from pins where user_id = ?)",
        (user_id,),
    )
