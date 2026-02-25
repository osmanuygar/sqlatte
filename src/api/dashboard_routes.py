# src/api/dashboard_routes.py
"""
SQLatte Dashboard API Routes
Handles dashboard generation, listing, refresh and deletion.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])


# ============================================
# REQUEST MODELS
# ============================================

class DashboardGenerateRequest(BaseModel):
    query_id: str
    title: Optional[str] = None           # if empty, uses favorite_name or question
    description: Optional[str] = ""


# ============================================
# DEPENDENCY HELPERS
# ============================================

def _get_manager():
    from src.core.dashboard_manager import get_dashboard_manager
    mgr = get_dashboard_manager()
    if mgr is None:
        raise HTTPException(status_code=503, detail="Dashboard Manager not initialized yet")
    return mgr


def _get_query_history():
    from src.core.query_history import query_history
    return query_history


def _get_db_provider():
    # Import at call-time to avoid circular import
    import sys
    import os
    # app.py exposes db_provider as module-level global
    app_module = sys.modules.get("src.api.app")
    if app_module and hasattr(app_module, "db_provider"):
        return app_module.db_provider
    raise HTTPException(status_code=503, detail="DB provider not available")


def _get_insights_engine():
    from src.core.llm_insights_engine import get_insights_engine
    return get_insights_engine()  # can be None → just return []


# ============================================
# ENDPOINTS
# ============================================

@router.get("")
async def list_dashboards():
    """
    List all dashboards (summary cards).
    GET /api/dashboards
    """
    mgr = _get_manager()
    dashboards = mgr.get_all_dashboards()
    return {
        "count": len(dashboards),
        "dashboards": dashboards
    }


@router.get("/stats")
async def dashboard_stats():
    """Basic dashboard statistics"""
    mgr = _get_manager()
    return mgr.get_stats()


@router.get("/{dashboard_id}")
async def get_dashboard(dashboard_id: str):
    """
    Get full dashboard with chart configs, data and insights.
    GET /api/dashboards/{id}
    """
    mgr = _get_manager()
    dashboard = mgr.get_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return dashboard


@router.post("/generate")
async def generate_dashboard(request: DashboardGenerateRequest):
    """
    Generate a new dashboard from a favorite query.

    Steps:
    1. Load favorite query by query_id
    2. Execute the SQL
    3. Run insights engine (if available)
    4. Analyze columns → charts + metric cards
    5. Persist and return dashboard

    POST /api/dashboards/generate
    Body: { "query_id": "...", "title": "optional", "description": "optional" }
    """
    mgr = _get_manager()
    qh = _get_query_history()

    # --- 1. Load favorite ---
    favorites = qh.get_favorites(limit=1000)
    favorite = next((f for f in favorites if f["id"] == request.query_id), None)

    if not favorite:
        raise HTTPException(
            status_code=404,
            detail=f"Favorite query '{request.query_id}' not found. "
                   "Make sure the query is saved to favorites."
        )

    sql = favorite.get("sql", "").strip()
    if not sql:
        raise HTTPException(status_code=400, detail="Favorite query has no SQL")

    question = favorite.get("question", "")
    favorite_name = favorite.get("favorite_name", "")

    # Title priority:
    # 1. User typed a title in the modal
    # 2. The favorite has a custom name (set when starring the query)
    # 3. Truncated question (first 60 chars)
    # 4. Fallback
    if request.title and request.title.strip():
        title = request.title.strip()
    elif favorite_name and favorite_name.strip():
        title = favorite_name.strip()
    elif question:
        clean_q = question.replace("\n", " ").strip()
        title = clean_q[:60] + ("\u2026" if len(clean_q) > 60 else "")
    else:
        title = "Dashboard"

    logger.info(
        f"\U0001f4ca Dashboard title resolved: \'{title}\' "
        f"(user_input=\'{request.title}\', fav_name=\'{favorite_name}\')"
    )

    # --- 2. Execute SQL ---
    try:
        db = _get_db_provider()
        columns, data = db.execute_query(sql)
        logger.info(f"📊 Dashboard query executed: {len(data)} rows, {len(columns)} columns")
    except Exception as e:
        logger.error(f"❌ Dashboard query execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query execution failed: {str(e)}")

    if not columns:
        raise HTTPException(status_code=400, detail="Query returned no columns")

    # --- 3. Generate insights ---
    insights = []
    try:
        engine = _get_insights_engine()
        if engine and engine.enabled:
            insights = engine.generate_insights(
                columns=columns,
                data=data,
                user_question=question,
                sql_query=sql
            )
            logger.info(f"💡 {len(insights)} insights generated")
    except Exception as e:
        logger.warning(f"⚠️ Insights generation skipped: {e}")

    # --- 4 & 5. Create dashboard ---
    try:
        dashboard = mgr.create_dashboard(
            query_id=request.query_id,
            title=title,
            question=question,
            sql=sql,
            columns=columns,
            data=data,
            insights=insights,
            description=request.description or ""
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"❌ Dashboard creation failed:\n{tb}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Dashboard creation failed",
                "message": str(e),
                "type": type(e).__name__,
                "hint": (
                    "This is often caused by non-JSON-serializable values in query results "
                    "(e.g. Python date/datetime, Decimal, bytes). "
                    "Check server logs for the full traceback."
                )
            }
        )

    return {
        "message": f"✅ Dashboard '{title}' created",
        "dashboard": dashboard
    }


@router.post("/{dashboard_id}/refresh")
async def refresh_dashboard(dashboard_id: str):
    """
    Re-execute the query and regenerate charts/insights for an existing dashboard.
    POST /api/dashboards/{id}/refresh
    """
    mgr = _get_manager()
    existing = mgr.get_dashboard(dashboard_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    sql = existing.get("sql", "").strip()
    if not sql:
        raise HTTPException(status_code=400, detail="Dashboard has no SQL to refresh")

    # Execute
    try:
        db = _get_db_provider()
        columns, data = db.execute_query(sql)
        logger.info(f"🔄 Dashboard refresh: {len(data)} rows")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query refresh failed: {str(e)}")

    # Insights
    insights = []
    try:
        engine = _get_insights_engine()
        if engine and engine.enabled:
            insights = engine.generate_insights(
                columns=columns,
                data=data,
                user_question=existing.get("question", ""),
                sql_query=sql
            )
    except Exception as e:
        logger.warning(f"⚠️ Insights skipped on refresh: {e}")

    updated = mgr.refresh_dashboard(dashboard_id, columns, data, insights)
    if not updated:
        raise HTTPException(status_code=500, detail="Refresh failed — check server logs for details")

    return {
        "message": "✅ Dashboard refreshed",
        "dashboard": updated
    }


@router.delete("/{dashboard_id}")
async def delete_dashboard(dashboard_id: str):
    """
    Delete a dashboard.
    DELETE /api/dashboards/{id}
    """
    mgr = _get_manager()
    deleted = mgr.delete_dashboard(dashboard_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    return {
        "message": "✅ Dashboard deleted",
        "dashboard_id": dashboard_id
    }