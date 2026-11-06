# Маршруты тегов: /api/tags/popular (тренды) и /api/tags/{tag}/pins
# (точное совпадение тега для страницы /tag/[slug]).
#
# Тег — свободный текст пользователя (в том числе кириллица), поэтому в пути
# он приходит URL-энкодом; Starlette декодирует его сам, отдельного латинского
# слага у тегов нет. /api/tags/popular объявлен раньше параметрического —
# «popular» иначе матчнулся бы как имя тега.

import sqlite3

from fastapi import APIRouter, Query

from .. import pins

router = APIRouter()


@router.get("/api/tags/popular")
def tags_popular(limit: int = Query(12, ge=1, le=50)) -> dict:
    return {"tags": pins.popular_tags(limit)}


@router.get("/api/tags/{tag}/pins")
def tags_pins(tag: str, limit: int = Query(60, ge=1, le=200)) -> dict:
    return {"pins": pins.pins_by_tag(tag, limit)}
