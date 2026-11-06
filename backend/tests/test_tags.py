# Теги: точная выборка для страницы /tag/[slug], тренды и адреса в sitemap.
#
# Тег — свободный текст пользователя: совпадение без учёта регистра, но
# строгое (подстрока «кошки» не должна выловить «кошкин дом»).

from conftest import upload


def _pin(user, tags: str):
    return upload(user, tags=tags).json()["pin"]


def test_pins_by_tag_matches_exactly_case_insensitive(client, user):
    _pin(user, tags="Кошки, дом")
    _pin(user, tags="кошкин дом")

    found = client.get("/api/tags/кошки/pins").json()["pins"]
    assert len(found) == 1
    # тег хранится как ввели: совпадение без регистра, запись — без правки
    assert any(t.lower() == "кошки" for t in found[0]["tags"])

    # тег с решёткой и другим регистром — тот же результат
    assert len(client.get("/api/tags/%23Кошки/pins").json()["pins"]) == 1
    # неизвестный тег — пусто, а не ошибка
    assert client.get("/api/tags/несуществует/pins").json()["pins"] == []


def test_popular_tags_orders_by_usage(client, user):
    _pin(user, tags="еда, завтрак")
    _pin(user, tags="Еда")
    _pin(user, tags="еда, кофе")

    tags = client.get("/api/tags/popular").json()["tags"]
    assert tags[0] == {"tag": "еда", "count": 3}
    assert {t["tag"] for t in tags} >= {"завтрак", "кофе"}


def test_tag_pins_limit_is_capped(client, user):
    for i in range(3):
        _pin(user, tags="рамки")
    assert len(client.get("/api/tags/рамки/pins", params={"limit": 2}).json()["pins"]) == 2
    assert client.get("/api/tags/рамки/pins", params={"limit": 999}).status_code == 422


def test_seo_lists_tag_pages(client, user):
    _pin(user, tags="вышивка")
    paths = [u["path"] for u in client.get("/api/seo/urls", params={"kind": "tags"}).json()["urls"]]
    assert "/tag/вышивка" in paths
    # lastmod = день последнего пина с тегом
    assert client.get("/api/seo/urls", params={"kind": "tags"}).json()["urls"][0]["lastmod"]
