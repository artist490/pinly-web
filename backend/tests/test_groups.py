# Группы по тематикам: создание, вступление, роли, публикация пинов.
#
# Ключевые гарантии: публикуют владелец и poster, обычный участник — 403;
# роли меняет только владелец; снапшот пина проверяется тем же контрактом,
# что у досок и чатов; владелец не может покинуть группу; жалоба на группу
# банит её владельца.

import sqlite3

from backend.db import DB_PATH

from conftest import PNG, upload


def db(sql, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _other(client, register, name="Другой"):
    other = register(display_name=name)
    return {"cookies": {"pinly_session": other.cookies["pinly_session"]}, "id": other.json()["user"]["id"]}


def _create_group(client, cookies, title="Рецепты со всего мира", **fields):
    body = {"title": title}
    body.update(fields)
    return client.post("/api/groups", json=body, cookies=cookies)


def _card(pin: dict) -> dict:
    """Карточка пина: тот же каркас, что доски и чаты кладут в снапшот."""
    return {k: pin[k] for k in ("id", "title", "width", "height")}


def test_group_requires_login_and_title(client, user):
    assert client.post("/api/groups", json={"title": ""}).status_code == 401
    assert client.post("/api/groups", json={"title": "  "}, cookies=user["cookies"]).status_code == 400


def test_create_join_leave_and_catalog(client, user, register):
    group = _create_group(client, user["cookies"], category="Рецепты").json()["group"]
    other = _other(client, register)

    # создатель сразу владелец и участник
    mine = client.get("/api/groups/mine", cookies=user["cookies"]).json()["groups"]
    assert mine[0]["id"] == group["id"] and mine[0]["myRole"] == "owner"
    assert mine[0]["membersCount"] == 1

    # свободное вступление: любой вошедший, идемпотентно
    assert client.post(f"/api/groups/{group['id']}/join", cookies=other["cookies"]).json() == {"ok": True}
    assert client.post(f"/api/groups/{group['id']}/join", cookies=other["cookies"]).status_code == 200
    card = client.get(f"/api/groups/{group['id']}").json()["group"]
    assert card["membersCount"] == 2

    # владелец уйти не может, участник — может
    assert client.post(f"/api/groups/{group['id']}/leave", cookies=user["cookies"]).status_code == 400
    assert client.post(f"/api/groups/{group['id']}/leave", cookies=other["cookies"]).status_code == 200
    assert client.get(f"/api/groups/{group['id']}").json()["group"]["membersCount"] == 1

    # каталог видит группу и фильтрует по категории
    catalog = client.get("/api/groups", params={"category": "Рецепты"}).json()["groups"]
    assert any(g["id"] == group["id"] for g in catalog)
    assert client.get("/api/groups", params={"q": "Рецепты со всего"}).json()["groups"]
    assert client.get("/api/groups", params={"q": "несуществует"}).json()["groups"] == []


def test_posting_requires_owner_or_poster(client, user, register):
    group = _create_group(client, user["cookies"]).json()["group"]
    member = _other(client, register, "Читатель")
    poster = _other(client, register, "Автор")
    client.post(f"/api/groups/{group['id']}/join", cookies=member["cookies"])
    client.post(f"/api/groups/{group['id']}/join", cookies=poster["cookies"])

    pin = upload(user, content=PNG).json()["pin"]
    url = f"/api/groups/{group['id']}/pins/{pin['id']}"

    # обычный участник публиковать не может
    assert client.put(url, json=_card(pin), cookies=member["cookies"]).status_code == 403

    # владелец выдаёт право публикации; менять роли может только владелец
    assert (
        client.post(
            f"/api/groups/{group['id']}/members/{poster['id']}/role",
            json={"role": "poster"},
            cookies=member["cookies"],
        ).status_code
        == 403
    )
    granted = client.post(
        f"/api/groups/{group['id']}/members/{poster['id']}/role",
        json={"role": "poster"},
        cookies=user["cookies"],
    )
    assert granted.json() == {"ok": True, "role": "poster"}

    # теперь poster публикует, снапшот виден в публичной карточке
    assert client.put(url, json=_card(pin), cookies=poster["cookies"]).status_code == 200
    feed = client.get(f"/api/groups/{group['id']}").json()["group"]["pins"]
    assert [p["id"] for p in feed] == [pin["id"]]

    # cureroka снапшота: карточка без обязательных полей отклоняется тем же
    # контрактом, что доски и чаты
    assert client.put(url, json={"id": pin["id"]}, cookies=poster["cookies"]).status_code == 400

    # владелец может снимать право
    client.post(
        f"/api/groups/{group['id']}/members/{poster['id']}/role",
        json={"role": "member"},
        cookies=user["cookies"],
    )
    assert client.put(url, json=_card(pin), cookies=poster["cookies"]).status_code == 403

    # уведомление о выданном праве получает участник
    items = client.get("/api/notifications", cookies=poster["cookies"]).json()["items"]
    assert any(i["type"] == "group_poster" for i in items)


def test_members_list_and_roles(client, user, register):
    group = _create_group(client, user["cookies"]).json()["group"]
    other = _other(client, register)
    client.post(f"/api/groups/{group['id']}/join", cookies=other["cookies"])

    listed = client.get(f"/api/groups/{group['id']}/members").json()["members"]
    roles = {m["id"]: m["role"] for m in listed}
    assert roles[user["id"]] == "owner" and roles[other["id"]] == "member"
    # чужой список участников не даёт кнопок управления
    assert all(m["canManage"] is False for m in listed)
    mine = client.get(f"/api/groups/{group['id']}/members", cookies=user["cookies"]).json()["members"]
    assert all(m["canManage"] for m in mine)


def test_group_update_delete_owner_only(client, user, register):
    group = _create_group(client, user["cookies"]).json()["group"]
    other = _other(client, register)

    assert (
        client.patch(
            f"/api/groups/{group['id']}",
            json={"title": "Новое название", "description": "Про еду", "category": "Рецепты"},
            cookies=other["cookies"],
        ).status_code
        == 403
    )
    updated = client.patch(
        f"/api/groups/{group['id']}",
        json={"title": "Новое название", "description": "Про еду", "category": "Рецепты"},
        cookies=user["cookies"],
    ).json()["group"]
    assert updated["title"] == "Новое название" and updated["category"] == "Рецепты"

    assert client.delete(f"/api/groups/{group['id']}", cookies=other["cookies"]).status_code == 403
    assert client.delete(f"/api/groups/{group['id']}", cookies=user["cookies"]).status_code == 204
    assert client.get(f"/api/groups/{group['id']}").status_code == 404


def test_remove_pin_by_adder_or_owner(client, user, register):
    group = _create_group(client, user["cookies"]).json()["group"]
    pin = upload(user, content=PNG).json()["pin"]
    client.put(
        f"/api/groups/{group['id']}/pins/{pin['id']}", json=_card(pin), cookies=user["cookies"]
    )
    stranger = _other(client, register)
    assert (
        client.delete(
            f"/api/groups/{group['id']}/pins/{pin['id']}", cookies=stranger["cookies"]
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/groups/{group['id']}/pins/{pin['id']}", cookies=user["cookies"]
        ).status_code
        == 204
    )
    assert client.get(f"/api/groups/{group['id']}").json()["group"]["pins"] == []


def test_report_group_bans_owner(client, user, register):
    group = _create_group(client, user["cookies"]).json()["group"]
    reporter = _other(client, register)
    report = client.post(
        "/api/reports",
        json={"target_type": "group", "target_id": group["id"], "reason": "spam"},
        cookies=reporter["cookies"],
    )
    assert report.status_code == 200
    queue = client.get("/api/admin/reports", cookies=user["cookies"]).json()["reports"]
    row = next(r for r in queue if r["targetId"] == group["id"])
    assert row["target"]["title"] == "Рецепты со всего мира"

    # вердикт ban_user по группе банит владельца группы
    resolved = client.post(
        f"/api/admin/reports/{row['id']}/resolve",
        json={"action": "ban_user"},
        cookies=reporter["cookies"],
    )
    assert resolved.status_code == 200
    assert db("select is_blocked from users where id = ?", (user["id"],))[0]["is_blocked"] == 1
