# Маршруты групп: каталог, вступление, публикация пинов и роли.
#
# /api/groups/mine объявлен раньше /api/groups/{group_id} — иначе «mine»
# матчнулся бы как id группы.

import sqlite3

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from .. import groups, notifications, ratelimit
from ..deps import current_user, optional_user
from ..schemas import GroupCreateBody, GroupRoleBody, GroupUpdateBody, pin_card_json

router = APIRouter()


@router.get("/api/groups")
def groups_catalog(
    category: str | None = None,
    q: str | None = None,
    limit: int = Query(40, ge=1, le=100),
) -> dict:
    return {"groups": groups.list_public(category, q, limit)}


@router.get("/api/groups/mine")
def groups_mine(me: sqlite3.Row = Depends(current_user)) -> dict:
    return {"groups": groups.list_mine(me["id"])}


@router.get("/api/groups/postable")
def groups_postable(me: sqlite3.Row = Depends(current_user)) -> dict:
    """Группы, где вошедший может публиковать (для меню сохранения пина)."""
    return {"groups": groups.postable_groups(me["id"])}


@router.post("/api/groups")
def group_create(
    body: GroupCreateBody, request: Request, me: sqlite3.Row = Depends(current_user)
) -> dict:
    ratelimit.rate_limit(request, "group_create", limit=50, window_s=3600.0)
    return {"group": groups.create(me["id"], body.title, body.description, body.category)}


@router.get("/api/groups/{group_id}")
def group_card(
    group_id: str, viewer: sqlite3.Row | None = Depends(optional_user)
) -> dict:
    return {"group": groups.public_group(group_id, viewer["id"] if viewer else None)}


@router.patch("/api/groups/{group_id}")
def group_update(
    group_id: str, body: GroupUpdateBody, me: sqlite3.Row = Depends(current_user)
) -> dict:
    return {"group": groups.update(me["id"], group_id, body.title, body.description, body.category)}


@router.delete("/api/groups/{group_id}")
def group_delete(group_id: str, me: sqlite3.Row = Depends(current_user)) -> Response:
    groups.delete(me["id"], group_id)
    return Response(status_code=204)


@router.post("/api/groups/{group_id}/join")
def group_join(
    group_id: str, request: Request, me: sqlite3.Row = Depends(current_user)
) -> dict:
    ratelimit.rate_limit(request, "group_join", limit=60, window_s=3600.0)
    groups.join(me["id"], group_id)
    return {"ok": True}


@router.post("/api/groups/{group_id}/leave")
def group_leave(group_id: str, me: sqlite3.Row = Depends(current_user)) -> dict:
    groups.leave(me["id"], group_id)
    return {"ok": True}


@router.get("/api/groups/{group_id}/members")
def group_members(
    group_id: str, viewer: sqlite3.Row | None = Depends(optional_user)
) -> dict:
    return {"members": groups.members(group_id, viewer["id"] if viewer else None)}


@router.post("/api/groups/{group_id}/members/{user_id}/role")
def group_member_role(
    group_id: str, user_id: str, body: GroupRoleBody, me: sqlite3.Row = Depends(current_user)
) -> dict:
    result = groups.set_role(me["id"], group_id, user_id, body.role)
    if body.role == "poster":
        notifications.notify_group_poster(me["id"], user_id)
    return result


@router.put("/api/groups/{group_id}/pins/{pin_id}")
async def group_pin_save(
    group_id: str,
    pin_id: str,
    request: Request,
    me: sqlite3.Row = Depends(current_user),
) -> dict:
    ratelimit.rate_limit(request, "group_pin", limit=200, window_s=3600.0)
    card = pin_card_json(await request.json(), pin_id)
    groups.add_pin(me["id"], group_id, pin_id, card)
    notifications.notify_group_pin(me["id"], group_id, pin_id)
    return JSONResponse({"ok": True})


@router.delete("/api/groups/{group_id}/pins/{pin_id}")
def group_pin_remove(
    group_id: str, pin_id: str, me: sqlite3.Row = Depends(current_user)
) -> Response:
    groups.remove_pin(me["id"], group_id, pin_id)
    return Response(status_code=204)
