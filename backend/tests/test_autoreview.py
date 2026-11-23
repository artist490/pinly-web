# Авто-модерация публикуемых пинов (backend/autoreview.py).
#
# Ключевые гарантии: без ключа модель не вызывается вовсе; чистый пин
# остаётся видимым; пин с высокой вероятностью нарушения скрывается и
# попадает в очередь с пометкой авто; «Отклонить» возвращает его в ленту;
# сбой внешнего сервиса не ломает публикацию; правка текста тоже
# проверяется. Сеть не трогается — вызов модели подменяется.

import sqlite3

import pytest

from backend import autoreview
from backend.db import DB_PATH

from conftest import PNG, upload


def db(sql, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


@pytest.fixture
def review(monkeypatch):
    """Ключ включён, _decide подменён: вердикты задаёт тест, а факт
    вызова виден в списке calls."""
    monkeypatch.setenv("EMBED_API_KEY", "test-key")
    holder = {"calls": 0, "verdicts": {}}

    async def fake_decide(state):
        holder["calls"] += 1
        return holder["verdicts"]

    monkeypatch.setattr(autoreview, "_decide", fake_decide)
    return holder


def _pin_row(pin_id):
    return db("select is_hidden from pins where id = ?", (pin_id,))[0]


def test_no_key_no_calls(client, user, monkeypatch):
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    calls = []

    async def spy(state):
        calls.append(state)

    monkeypatch.setattr(autoreview, "_decide", spy)
    upload(user, content=PNG)
    assert calls == []


def test_clean_pin_stays_visible(client, user, review):
    review["verdicts"] = {"is_spam": 0.02, "is_offensive": 0.01, "is_copyright": 0.03}
    pin = upload(user, content=PNG).json()["pin"]
    assert review["calls"] == 1
    assert _pin_row(pin["id"])["is_hidden"] == 0
    # чистый пин не порождает жалоб в очереди
    rows = db("select * from reports where target_id = ?", (pin["id"],))
    assert rows == []


def test_flagged_pin_hidden_and_queued(client, user, review):
    review["verdicts"] = {"is_spam": 0.02, "is_offensive": 0.93, "is_copyright": 0.1}
    pin = upload(user, content=PNG, title="Проверка авто").json()["pin"]
    assert _pin_row(pin["id"])["is_hidden"] == 1
    rows = db("select * from reports where target_id = ?", (pin["id"],))
    assert len(rows) == 1
    assert rows[0]["auto_review"] == 1
    assert rows[0]["reporter_id"] is None
    assert rows[0]["reason"] == "offensive"
    assert "is_offensive=0.93" in rows[0]["detail"]
    # пин исчез из публичной выдачи
    assert client.get(f"/api/pin/{pin['id']}").status_code == 404


def test_dismiss_restores_auto_hidden_pin(client, user, review):
    review["verdicts"] = {"is_spam": 0.95, "is_offensive": 0.01, "is_copyright": 0.01}
    pin = upload(user, content=PNG).json()["pin"]
    report_id = db(
        "select id from reports where target_id = ? and auto_review = 1", (pin["id"],)
    )[0]["id"]
    assert (
        client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"action": "dismiss"},
            cookies=user["cookies"],
        ).status_code
        == 200
    )
    # человек отверг вердикт машины — пин вернулся
    assert _pin_row(pin["id"])["is_hidden"] == 0
    assert client.get(f"/api/pin/{pin['id']}").status_code == 200


def test_model_failure_does_not_block_publish(client, user, monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "test-key")

    async def broken(state):
        raise RuntimeError("сервис недоступен")

    monkeypatch.setattr(autoreview, "_decide", broken)
    response = upload(user, content=PNG)
    assert response.status_code == 200
    assert _pin_row(response.json()["pin"]["id"])["is_hidden"] == 0


def test_pin_update_is_rechecked(client, user, review):
    review["verdicts"] = {"is_spam": 0.01, "is_offensive": 0.01, "is_copyright": 0.01}
    pin = upload(user, content=PNG).json()["pin"]
    assert review["calls"] == 1
    # дописали текст — та же проверка, что и при публикации
    review["verdicts"] = {"is_spam": 0.9, "is_offensive": 0.01, "is_copyright": 0.01}
    response = client.patch(
        f"/api/pins/{pin['id']}",
        json={"description": "теперь спам"},
        cookies=user["cookies"],
    )
    assert response.status_code == 200
    assert review["calls"] == 2
    assert _pin_row(pin["id"])["is_hidden"] == 1


def test_admin_queue_carries_auto_badge(client, user, review):
    review["verdicts"] = {"is_spam": 0.95, "is_offensive": 0.01, "is_copyright": 0.01}
    pin = upload(user, content=PNG, title="Авто-кейс").json()["pin"]
    queue = client.get("/api/admin/reports", cookies=user["cookies"]).json()["reports"]
    mine = [r for r in queue if r["targetId"] == pin["id"]]
    assert len(mine) == 1
    assert mine[0]["autoReview"] is True
    assert "is_spam=0.95" in mine[0]["detail"]
