# Закрепление правок ревью: снапшот карточки не должен проносить чужие схемы,
# кука сессии не должен писаться по клиентскому заголовку, а удаление
# аккаунта — оставлять открытый email в журнале согласий.

import pytest

from conftest import upload

from backend.db import connection

BOARD = {"title": "Доска", "is_secret": False, "if_missing": False}


def _card(pin_id: str, **fields) -> dict:
    card = {"id": pin_id, "title": "Пин", "width": 800, "height": 1200}
    card.update(fields)
    return card


def _save_into_board(user, card: dict) -> int:
    client, cookies = user["client"], user["cookies"]
    board_id = client.post("/api/boards", json=BOARD, cookies=cookies).json()["board"]["id"]
    return client.put(
        f"/api/boards/{board_id}/pins/{card['id']}", json=card, cookies=cookies
    ).status_code


@pytest.mark.parametrize(
    "bad",
    [
        {"sourceUrl": "javascript:alert(1)"},
        {"pageUrl": "javascript:alert(1)"},
        {"authorAvatar": "data:text/html,<script>alert(1)</script>"},
        {"url": "  https://example.test"},  # схема не в начале строки — не ссылка
        {"sourceUrl": 42},  # не строка
    ],
)
def test_board_snapshot_rejects_non_http_urls(user, bad):
    """Карточка рисуется у чужих людей: схема обязана остаться http(s) или
    относительным путём, иначе первый же href превратит хранимое в XSS."""
    assert _save_into_board(user, _card("pin-1", **bad)) == 400


def test_board_snapshot_accepts_real_urls(user):
    """Относительный путь нашего прокси и https источника — норма: под
    запрет не должны попадать легальные карточки ленты."""
    for card in (
        _card("pin-2", sourceUrl="/api/img?u=https://openverse.org/a.jpg"),
        _card("pin-3", sourceUrl="https://images.weserv.nl/?url=a", pageUrl="https://a.test"),
    ):
        assert _save_into_board(user, card) in (200, 204)


def test_session_cookie_ignores_forged_forwarded_proto(client, monkeypatch):
    """Клиент не голосует, ставить ли Secure: без явного доверия прокси
    заголовок x-forwarded-proto обязан игнорироваться (иначе downgrade
    одной строчкой в curl)."""
    monkeypatch.delenv("PINLY_TRUST_PROXY", raising=False)
    response = client.post(
        "/api/auth/login",
        json={"email": "nope@example.test", "password": "secret12345"},
        headers={"x-forwarded-proto": "https"},
    )
    assert "Secure" not in response.headers.get("set-cookie", "")


def test_session_cookie_secure_behind_trusted_proxy(client, monkeypatch):
    """За своим прокси тот же заголовок, наоборот, обязан давать Secure —
    иначе кука уедет по http."""
    monkeypatch.setenv("PINLY_TRUST_PROXY", "1")
    email = "proxy@example.test"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret12345", "consent": True},
    )
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "secret12345"},
        headers={"x-forwarded-proto": "https"},
    )
    assert "Secure" in response.headers.get("set-cookie", "")


def test_account_erasure_pseudonymises_consent_log(user, register):
    """Факт согласия остаётся доказательством, открытый email — уходит:
    после удаления аккаунта хранить его не на основании чего либо."""
    account = register(email="keep@example.test", display_name="Ася")
    cookies = account.cookies
    user_id = account.json()["user"]["id"]

    with connection() as conn:
        before = conn.execute(
            "select email from consent_log where user_id = ?", (user_id,)
        ).fetchone()["email"]
    assert before == "keep@example.test"

    assert user["client"].delete("/api/auth/account", cookies=cookies).status_code == 200

    with connection() as conn:
        rows = conn.execute(
            "select email, kind, doc_version from consent_log where user_id = ?", (user_id,)
        ).fetchall()
    assert rows, "журнал согласий не должен исчезать вместе с аккаунтом"
    for row in rows:
        assert row["email"].startswith("sha256:") and "@" not in row["email"]
        assert row["doc_version"] and row["kind"]


# ── количество запросов: пакеты должны оставаться пакетами ───────────────
# N+1 возвращается молча: ответ тот же, медленнее только под нагрузкой.
# Поэтому проверяем не тело ответа, а число execute() на один эндпоинт.

@pytest.fixture
def sql_counter(monkeypatch):
    """Возвращает счётчик запросов для модуля: connection() оборачивается
    так, чтобы pragma-строки (они идут до yield) внутрь не попадали."""
    import contextlib

    def instrument(module):
        seen: list[str] = []
        real = module.connection

        @contextlib.contextmanager
        def counted():
            with real() as conn:
                conn.set_trace_callback(seen.append)
                yield conn

        monkeypatch.setattr(module, "connection", counted)
        return seen

    return instrument


def test_chat_list_does_not_query_per_chat(client, register, user, sql_counter):
    """5 собеседников не должны означать 25 запросов к SQLite."""
    from backend import chats

    me = user["cookies"]
    for _ in range(5):
        peer = register()
        client.post(
            "/api/chats",
            json={"userId": peer.json()["user"]["id"]},
            cookies=me,
        )
    seen = sql_counter(chats)
    before = len(seen)

    response = client.get("/api/chats", cookies=me)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 5

    queries = len(seen) - before
    assert queries <= 6, f"список чатов делает {queries} запросов — вернулся N+1"


def test_user_pin_list_does_not_query_per_pin(client, user, sql_counter):
    """Профиль с 6 загрузками не должен стоить 18+ запросов на карточки."""
    from backend import pins

    for i in range(6):
        response = upload(user, title=f"Пин {i}")
        assert response.status_code == 200

    seen = sql_counter(pins)
    before = len(seen)
    response = client.get("/api/user-pins?limit=6")
    assert response.status_code == 200
    assert len(response.json()["pins"]) == 6

    queries = len(seen) - before
    assert queries <= 5, f"список пинов делает {queries} запросов — вернулся N+1"


# ── владельческие данные закрыты по умолчанию ────────────────────────────
# Раньше «PINLY_OWNER_EMAIL не задан» означало «можно всем вошедшим»: одна
# забытая переменная на боевом сервере отдавала бан пользователей любому
# зарегистрированному. Теперь отказ конфигурации закрывает доступ.


def test_admin_panel_closed_without_owner_or_local_flag(client, register, monkeypatch):
    monkeypatch.delenv("PINLY_OWNER_EMAIL", raising=False)
    monkeypatch.delenv("PINLY_ENV", raising=False)
    monkeypatch.delenv("PINLY_ALLOW_LOCAL_ADMIN", raising=False)
    someone = register()
    assert client.get("/api/admin/reports", cookies=someone.cookies).status_code == 404
    assert client.get("/api/ev/summary", cookies=someone.cookies).status_code == 404
    # жалобы — не админ-зона: их пишут обычные пользователи
    assert client.post(
        "/api/reports",
        json={"target_type": "pin", "target_id": "ov-1", "reason": "spam"},
        cookies=someone.cookies,
    ).status_code == 200


def test_local_admin_flag_is_ignored_in_production(client, register, monkeypatch):
    """Локальный обход не должен пережить переезд стенда в прод."""
    monkeypatch.setenv("PINLY_ALLOW_LOCAL_ADMIN", "1")
    monkeypatch.setenv("PINLY_ENV", "production")
    monkeypatch.delenv("PINLY_OWNER_EMAIL", raising=False)
    someone = register()
    assert client.get("/api/admin/reports", cookies=someone.cookies).status_code == 404


# ── выход отзывает сессию, а не только стирает куку ──────────────────────


def test_logout_revokes_the_token_itself(client, register):
    """Скопированная заранее кука обязана умереть вместе с выходом, а не
    жить оставшиеся 30 дней."""
    account = register()
    stolen = {"pinly_session": account.cookies["pinly_session"]}
    assert client.get("/api/auth/me", cookies=stolen).status_code == 200

    assert client.post("/api/auth/logout", cookies=stolen).status_code == 200

    # тот же самый токен больше ничего не открывает
    assert client.get("/api/auth/me", cookies=stolen).status_code == 401
    assert client.get("/api/chats", cookies=stolen).status_code == 401


def test_login_after_logout_issues_a_working_session(client, register):
    """Отзыв не должен ломать повторный вход тем же человеком."""
    account = register(email="relogin@example.test")
    old = {"pinly_session": account.cookies["pinly_session"]}
    client.post("/api/auth/logout", cookies=old)

    fresh = client.post(
        "/api/auth/login",
        json={"email": "relogin@example.test", "password": "secret12345"},
    )
    assert fresh.status_code == 200
    cookies = {"pinly_session": fresh.cookies["pinly_session"]}
    assert client.get("/api/auth/me", cookies=cookies).status_code == 200


def test_session_token_carries_revision(client, register):
    """sv в токене — то, с чем сверяется база; без него отзыв не работает."""
    from backend.session import SESSION_COOKIE, jwt_decode

    account = register()
    payload = jwt_decode(account.cookies[SESSION_COOKIE])
    assert payload["sv"] == 0


# ── заголовки безопасности на ответах API ────────────────────────────────
# Страницы получают их из next.config.ts, а /api/* уходит на бэкенд
# rewrite'ом, где заголовки Next не применяются. Без этой прослойки JSON
# остался бы без nosniff, и браузер мог бы исполнить подменённый ответ.


def test_api_responses_carry_security_headers(client):
    for path in ("/healthz", "/api/saves-count", "/api/user-pins"):
        response = client.get(path)
        assert response.headers["x-content-type-options"] == "nosniff", path
        assert response.headers["x-frame-options"] == "DENY", path
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin", path
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"], path


def test_uploaded_files_are_served_without_document_csp(client, user):
    """Файл открывают прямой навигацией: CSP там применяется к документу и
    мешала бы встроенному просмотрщику видео. nosniff и frame-запрет — есть."""
    source = upload(user).json()["pin"]["sourceUrl"]
    response = client.get(source)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" not in response.headers
