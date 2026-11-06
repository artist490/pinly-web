# Маршруты модерации: POST /api/reports — жалобы вошедших,
# /api/admin/reports* — очередь и вердикты за RequireAdmin.

import sqlite3

from fastapi import APIRouter, Depends, Query, Request

from .. import moderation, ratelimit
from ..deps import current_user, require_admin
from ..schemas import ReportBody, ResolveBody

router = APIRouter()


@router.post("/api/reports")
def report_create(body: ReportBody, request: Request, me: sqlite3.Row = Depends(current_user)) -> dict:
    ratelimit.rate_limit(request, "report", limit=20, window_s=3600.0)
    report_id = moderation.create_report(me["id"], body.target_type, body.target_id, body.reason)
    return {"ok": True, "id": report_id}


@router.get("/api/admin/reports")
def admin_reports(
    limit: int = Query(100, ge=1, le=200), _: sqlite3.Row = Depends(require_admin)
) -> dict:
    return {"reports": moderation.open_reports(limit)}


@router.post("/api/admin/reports/{report_id}/resolve")
def admin_resolve(
    report_id: str, body: ResolveBody, request: Request, me: sqlite3.Row = Depends(require_admin)
) -> dict:
    ratelimit.rate_limit(request, "resolve", limit=120, window_s=3600.0)
    return moderation.resolve_report(me["id"], report_id, body.action)
