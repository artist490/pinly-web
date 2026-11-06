# Маршруты соцблока: /api/users* (профили, подписки), комментарии,
# /api/feed/subscriptions.

import sqlite3

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import notifications, ratelimit, social
from ..deps import current_user, optional_user
from ..schemas import CommentBody

router = APIRouter()


@router.get("/api/users/{user_id}")
def user_profile(user_id: str, viewer: sqlite3.Row | None = Depends(optional_user)) -> dict:
    return {"user": social.profile(user_id, viewer["id"] if viewer else None)}


@router.get("/api/users/{user_id}/pins")
def user_pins(user_id: str, limit: int | None = Query(None, ge=1, le=200)) -> dict:
    """Пины автора. Без ?limit= — все, как было до появления параметра;
    потолок 200 — чтобы страница мастера не отдавала сотни карточек в HTML.
    """
    return {"pins": social.user_pins(user_id, limit)}


@router.get("/api/users/{user_id}/boards")
def user_boards(user_id: str) -> dict:
    """Публичные (не секретные) доски пользователя."""
    return {"boards": social.user_boards(user_id)}


@router.post("/api/users/{user_id}/follow")
def follow(user_id: str, request: Request, me: sqlite3.Row = Depends(current_user)) -> dict:
    ratelimit.rate_limit(request, "follow", limit=60, window_s=3600.0)
    social.follow(me["id"], user_id)
    notifications.notify_follow(me["id"], user_id)
    return {"ok": True}


@router.delete("/api/users/{user_id}/follow")
def unfollow(user_id: str, me: sqlite3.Row = Depends(current_user)) -> dict:
    social.unfollow(me["id"], user_id)
    return {"ok": True}


@router.get("/api/feed/subscriptions")
def subscriptions_feed(me: sqlite3.Row = Depends(current_user)) -> dict:
    """Загрузки пользователей, на которых подписан + их публичные доски."""
    return social.subscriptions_feed(me["id"])


@router.get("/api/pin/{pin_id}/comments")
def comments_list(
    pin_id: str, viewer: sqlite3.Row | None = Depends(optional_user)
) -> dict:
    return {"comments": social.list_comments(pin_id, viewer["id"] if viewer else None)}


@router.post("/api/pin/{pin_id}/comments")
def comments_create(
    pin_id: str, body: CommentBody, request: Request, me: sqlite3.Row = Depends(current_user)
) -> dict:
    ratelimit.rate_limit(request, "comment", limit=30, window_s=3600.0)
    comment_id = social.add_comment(me["id"], pin_id, body.text, body.parent_id)
    if body.parent_id:
        # ответ уведомляет автора родительского комментария
        parent_author = social.parent_author_id(body.parent_id)
        if parent_author:
            notifications.notify_reply(me["id"], parent_author, pin_id)
    else:
        notifications.notify_comment(me["id"], pin_id)
    return {"ok": True, "id": comment_id}


@router.delete("/api/comments/{comment_id}")
def comments_delete(comment_id: str, me: sqlite3.Row = Depends(current_user)) -> Response:
    social.delete_comment(me["id"], comment_id)
    return Response(status_code=204)


@router.put("/api/comments/{comment_id}/like")
def comment_like(comment_id: str, request: Request, me: sqlite3.Row = Depends(current_user)) -> dict:
    ratelimit.rate_limit(request, "comment_like", limit=300, window_s=60.0)
    likes = social.like_comment(me["id"], comment_id)
    notifications.notify_comment_like(me["id"], comment_id)
    return {"ok": True, "likes": likes}


@router.delete("/api/comments/{comment_id}/like")
def comment_unlike(comment_id: str, me: sqlite3.Row = Depends(current_user)) -> dict:
    return {"ok": True, "likes": social.unlike_comment(me["id"], comment_id)}
