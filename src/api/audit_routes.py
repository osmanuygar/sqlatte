"""
Audit Log API Routes
"""

from datetime import datetime
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from typing import Optional
from src.core.audit_log_db import audit_log_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/logs")
async def get_audit_logs(
    session_id: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    model_name: Optional[str] = Query(None),
    widget_type: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=8760),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if audit_log_db is None:
        return {"logs": [], "error": "Audit logging is disabled"}
    logs = audit_log_db.get_logs(
        session_id=session_id,
        operation_type=operation_type,
        model_name=model_name,
        widget_type=widget_type,
        hours=hours,
        limit=limit,
        offset=offset,
    )
    return {"logs": logs, "count": len(logs)}


@router.get("/summary")
async def get_audit_summary(hours: int = Query(24, ge=1, le=8760)):
    if audit_log_db is None:
        return {"error": "Audit logging is disabled"}
    return audit_log_db.get_summary(hours=hours)


@router.get("/export/csv")
async def export_audit_csv(
    session_id: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    widget_type: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=8760),
):
    if audit_log_db is None:
        return {"error": "Audit logging is disabled"}
    csv_content = audit_log_db.export_csv(
        session_id=session_id,
        operation_type=operation_type,
        widget_type=widget_type,
        hours=hours,
    )
    filename = f"audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/daily-trend")
async def get_audit_daily_trend(days: int = Query(30, ge=1, le=180)):
    if audit_log_db is None:
        return {"error": "Audit logging is disabled", "days": []}
    return audit_log_db.get_daily_trend(days=days)


@router.get("/top-users")
async def get_audit_top_users(
    days: int = Query(30, ge=1, le=180),
    limit: int = Query(10, ge=1, le=50),
):
    if audit_log_db is None:
        return {"error": "Audit logging is disabled", "users": []}
    return audit_log_db.get_top_users(days=days, limit=limit)
