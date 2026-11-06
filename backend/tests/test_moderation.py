# Модерация: жалобы, скрытие пинов, бан аккаунта и админ-гейт.
#
# Ключевые гарантии: жалоба требует входа и валидной цели, дубликат не плодит
# очередь, скрытый пин исчезает из всех выборок (деталь, лента, поиск, теги,
# sitemap), забаненный не входит и теряет сессию, панель в проде заперта
# email владельца из окружения.

import sqlite3

import pytest

from backend.db import DB_PATH

from conftest import PNG, upload


def db(sql, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _other(client, register):
    other = register(display_name="Жалобщик")
    return {"cookies": {"pinly_session": other.cookies["pinly_session"]}, "id": other.json()["user"]["id"]}


def _report(client, cookies, target_type, target_id, reason="spam"):
    return client.post(
        "/api/reports",
        json={"target_type": target_type, "target_id": target_id, "reason": reason},
        cookies=cookies,
    )


def test_report_requires_login_and_validates(client, user, register):
    pin = upload(user, content=PNG).json()["pin"]
    assert _report(client, None, "pin", pin["id"]).status_code == 401

    other = _other(client, register)
    assert _report(client, other["cookies"], "photo", pin["id"]).status_code == 400
    assert _report(client, other["cookies"], "pin", pin["id"], reason="обида").status_code == 400
    assert _report(client, other["cookies"], "pin", "x" * 200).status_code == 400


def test_report_dedup_and_queue(client, user, register):
    pin = upload(user, content=PNG).json()["pin"]
    other = _other(client, register)

    first = _report(client, other["cookies"], "pin", pin["id"])
    assert first.status_code == 200
    # тот же человек на ту же цель второй раз — очередь не засоряет
    assert _report(client, other["cookies"], "pin", pin["id"]).status_code == 409
    # другой человек на ту же цель — отдельная жалоба
    third = _other(client, register)
    assert _report(client, third["cookies"], "pin", pin["id"]).status_code == 200

    queue = client.get("/api/admin/reports", cookies=user["cookies"]).json()["reports"]
    mine = [r for r in queue if r["targetId"] == pin["id"]]
    assert len(mine) == 2
    assert mine[0]["targetType"] == "pin"
    assert mine[0]["reason"] == "spam"
    assert mine[0]["target"]["exists"] is True


def test_report_carries_pin_title(client, user, register):
    pin = upload(user, content=PNG, title="Подозрительный пин").json()["pin"]
    other = _other(client, register)
    _report(client, other["cookies"], "pin", pin["id"], reason="copyright")

    queue = client.get("/api/admin/reports", cookies=user["cookies"]).json()["reports"]
    assert queue[0]["target"]["title"] == "Подозрительный пин"


def test_hide_pin_removes_it_from_everywhere(client, user, register):
    pin = upload(user, content=PNG, tags="рамки", title="Подозрительный пин").json()["pin"]
    other = _other(client, register)
    report_id = _report(client, other["cookies"], "pin", pin["id"]).json()["id"]

    resolved = client.post(
        f"/api/admin/reports/{report_id}/resolve",
        json={"action": "hide_pin"},
        cookies=user["cookies"],
    )
    assert resolved.status_code == 200

    # деталь — 404, из всех выборок пин исчез (база общая на прогон —
    # сверяем по id, а не по пустоте списка)
    assert client.get(f"/api/pin/{pin['id']}").status_code == 404
    listed = client.get("/api/user-pins?limit=20").json()["pins"]
    assert pin["id"] not in [p["id"] for p in listed]
    assert client.get("/api/user-pins", params={"q": "Подозрительный"}).json()["pins"] == []
    assert client.get("/api/tags/рамки/pins").json()["pins"] == []
    rows = db("select is_hidden from pins where id = ?", (pin["id"],))
    assert rows[0]["is_hidden"] == 1

    queue = client.get("/api/admin/reports", cookies=user["cookies"]).json()["reports"]
    assert all(r["id"] != report_id for r in queue)


def test_hide_pin_rejects_non_pin_target(client, user, register):
    other = _other(client, register)
    report_id = _report(client, other["cookies"], "user", other["id"]).json()["id"]
    assert (
        client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"action": "hide_pin"},
            cookies=user["cookies"],
        ).status_code
        == 400
    )


def test_ban_user_blocks_login_and_session(client, user, register):
    victim = register(display_name="Нарушитель")
    victim_cookies = {"pinly_session": victim.cookies["pinly_session"]}
    victim_id = victim.json()["user"]["id"]
    upload({"client": client, "cookies": victim_cookies}, content=PNG)  # пин нарушителя живёт

    report_id = _report(client, user["cookies"], "user", victim_id, reason="spam").json()["id"]
    assert (
        client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"action": "ban_user"},
            cookies=user["cookies"],
        ).status_code
        == 200
    )

    # сессия больше ничего не открывает, вход отклонён, данные на месте
    assert client.get("/api/auth/me", cookies=victim_cookies).status_code == 401
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "не важно", "password": "не важно"},
        ).status_code
        == 401
    )
    login = client.post(
        "/api/auth/login",
        json={"email": victim.json()["user"]["email"], "password": "secret12345"},
    )
    assert login.status_code == 403
    assert db("select is_blocked from users where id = ?", (victim_id,))[0]["is_blocked"] == 1


def test_ban_rejects_self(client, user):
    report_id = _report(client, user["cookies"], "user", user["id"]).json()["id"]
    assert (
        client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"action": "ban_user"},
            cookies=user["cookies"],
        ).status_code
        == 400
    )


def test_dismiss_resolves_without_action(client, user, register):
    other = _other(client, register)
    report_id = _report(client, other["cookies"], "pin", "ov-неизвестный").json()["id"]
    assert (
        client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"action": "dismiss"},
            cookies=user["cookies"],
        ).status_code
        == 200
    )
    rows = db("select status from reports where id = ?", (report_id,))
    assert rows[0]["status"] == "resolved"
    # повторный вердикт по решённой жалобе — конфликт, а не новое решение
    assert client.post(
        f"/api/admin/reports/{report_id}/resolve",
        json={"action": "dismiss"},
        cookies=user["cookies"],
    ).status_code == 409


@pytest.fixture
def owner_env(monkeypatch):
    monkeypatch.setenv("PINLY_OWNER_EMAIL", "owner@example.test")
    monkeypatch.delenv("PINLY_ENV", raising=False)


def test_admin_gate_owner_email(client, register, owner_env):
    owner = register(email="owner@example.test")
    stranger = register(display_name="Чужой")

    assert client.get("/api/admin/reports", cookies=stranger.cookies).status_code == 403
    assert client.get("/api/admin/reports", cookies=owner.cookies).status_code == 200
    # флаг isAdmin виден фронту, чтобы рисовать ссылку на панель
    assert client.get("/api/auth/me", cookies=owner.cookies).json()["user"]["isAdmin"] is True
    assert client.get("/api/auth/me", cookies=stranger.cookies).json()["user"]["isAdmin"] is False


def test_admin_gate_locked_in_production_without_owner(client, register, monkeypatch):
    monkeypatch.setenv("PINLY_ENV", "production")
    monkeypatch.delenv("PINLY_OWNER_EMAIL", raising=False)
    someone = register()
    assert client.get("/api/admin/reports", cookies=someone.cookies).status_code == 404
    assert _report(client, someone.cookies, "pin", "ov-1").status_code == 200  # жалобы — не админ-зона
