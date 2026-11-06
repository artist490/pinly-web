# Ответы на комментарии (один уровень) и лайки комментариев.
#
# Ключевые гарантии: ответ привязан к своему пину и к комментарию верхнего
# уровня, ответ на ответ невозможен, удаление родителя уносит ответы и лайки,
# уведомление об ответе уходит автору родителя, а не владельцу пина.

import sqlite3

from backend.db import DB_PATH

from conftest import PNG, upload


def db(sql, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _other(client, register):
    other = register(display_name="Другой")
    return {"cookies": {"pinly_session": other.cookies["pinly_session"]}, "id": other.json()["user"]["id"]}


def test_reply_is_nested_under_parent(client, user, register):
    pin = upload(user, content=PNG).json()["pin"]
    top_id = client.post(
        f"/api/pin/{pin['id']}/comments", json={"text": "верхний"}, cookies=user["cookies"]
    ).json()["id"]
    other = _other(client, register)
    reply_id = client.post(
        f"/api/pin/{pin['id']}/comments",
        json={"text": "ответ", "parent_id": top_id},
        cookies=other["cookies"],
    ).json()["id"]

    listed = client.get(f"/api/pin/{pin['id']}/comments").json()["comments"]
    assert len(listed) == 1
    assert listed[0]["id"] == top_id
    assert [r["id"] for r in listed[0]["replies"]] == [reply_id]
    assert listed[0]["replies"][0]["author"]["id"] == other["id"]


def test_reply_rejects_foreign_pin_and_nested_parent(client, user, register):
    pin = upload(user, content=PNG).json()["pin"]
    other_pin = upload(user, content=PNG).json()["pin"]
    top_id = client.post(
        f"/api/pin/{pin['id']}/comments", json={"text": "верхний"}, cookies=user["cookies"]
    ).json()["id"]
    reply_id = client.post(
        f"/api/pin/{pin['id']}/comments",
        json={"text": "ответ", "parent_id": top_id},
        cookies=user["cookies"],
    ).json()["id"]

    other = _other(client, register)
    # чужой пин не принимает чужой комментарий как родителя
    assert (
        client.post(
            f"/api/pin/{other_pin['id']}/comments",
            json={"text": "не туда", "parent_id": top_id},
            cookies=other["cookies"],
        ).status_code
        == 400
    )
    # ответ на ответ — тоже нет: глубина ровно один уровень
    assert (
        client.post(
            f"/api/pin/{pin['id']}/comments",
            json={"text": "второй уровень", "parent_id": reply_id},
            cookies=other["cookies"],
        ).status_code
        == 400
    )
    assert client.post(
        f"/api/pin/{pin['id']}/comments",
        json={"text": "неизвестный родитель", "parent_id": "no-such-comment"},
        cookies=other["cookies"],
    ).status_code == 404


def test_comment_likes_count_and_toggle(client, user, register):
    pin = upload(user, content=PNG).json()["pin"]
    comment_id = client.post(
        f"/api/pin/{pin['id']}/comments", json={"text": "лайкни меня"}, cookies=user["cookies"]
    ).json()["id"]
    other = _other(client, register)

    assert client.put(f"/api/comments/{comment_id}/like").status_code == 401
    put = client.put(f"/api/comments/{comment_id}/like", cookies=other["cookies"]).json()
    assert put["likes"] == 1
    # повторный лайк идемпотентен
    assert client.put(f"/api/comments/{comment_id}/like", cookies=other["cookies"]).json()["likes"] == 1

    listed = client.get(f"/api/pin/{pin['id']}/comments").json()["comments"]
    assert listed[0]["likes"] == 1
    assert listed[0]["likedByMe"] is False  # аноним
    mine = client.get(f"/api/pin/{pin['id']}/comments", cookies=other["cookies"]).json()["comments"]
    assert mine[0]["likes"] == 1 and mine[0]["likedByMe"] is True

    assert client.delete(f"/api/comments/{comment_id}/like", cookies=other["cookies"]).json()["likes"] == 0


def test_reply_notifies_comment_author_not_pin_owner(client, user, register):
    # пин пользователя `user`, комментарий пишет `commenter`, отвечает `replier`:
    # уведомление получает commenter, а не владелец пина
    pin = upload(user, content=PNG).json()["pin"]
    commenter = _other(client, register)
    top_id = client.post(
        f"/api/pin/{pin['id']}/comments", json={"text": "вопрос"}, cookies=commenter["cookies"]
    ).json()["id"]
    replier = _other(client, register)
    client.post(
        f"/api/pin/{pin['id']}/comments",
        json={"text": "ответ", "parent_id": top_id},
        cookies=replier["cookies"],
    )

    author_items = client.get("/api/notifications", cookies=commenter["cookies"]).json()["items"]
    assert any(i["type"] == "reply" and i["actor"]["id"] == replier["id"] for i in author_items)
    owner_items = client.get("/api/notifications", cookies=user["cookies"]).json()["items"]
    assert not any(i["type"] == "reply" for i in owner_items)


def test_comment_like_notifies_author(client, user, register):
    pin = upload(user, content=PNG).json()["pin"]
    commenter = _other(client, register)
    comment_id = client.post(
        f"/api/pin/{pin['id']}/comments", json={"text": "текст"}, cookies=commenter["cookies"]
    ).json()["id"]
    client.put(f"/api/comments/{comment_id}/like", cookies=user["cookies"])

    items = client.get("/api/notifications", cookies=commenter["cookies"]).json()["items"]
    assert any(i["type"] == "comment_like" and i["actor"]["id"] == user["id"] for i in items)


def test_deleting_parent_removes_replies_and_likes(client, user, register):
    pin = upload(user, content=PNG).json()["pin"]
    top_id = client.post(
        f"/api/pin/{pin['id']}/comments", json={"text": "родитель"}, cookies=user["cookies"]
    ).json()["id"]
    other = _other(client, register)
    reply_id = client.post(
        f"/api/pin/{pin['id']}/comments",
        json={"text": "ответ", "parent_id": top_id},
        cookies=other["cookies"],
    ).json()["id"]
    client.put(f"/api/comments/{reply_id}/like", cookies=user["cookies"])

    client.delete(f"/api/comments/{top_id}", cookies=user["cookies"])
    assert db("select * from comments where id = ?", (top_id,)) == []
    assert db("select * from comments where id = ?", (reply_id,)) == []
    assert db("select * from comment_likes where comment_id = ?", (reply_id,)) == []
