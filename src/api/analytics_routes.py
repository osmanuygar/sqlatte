"""
SQLatte Analytics API Routes
Provides analytics data for dashboard and monitoring
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Dict, List
from datetime import datetime, timedelta

from src.core.analytics_db_postgres import analytics_db
from src.core.query_history import query_history
from src.core.error_utils import server_error

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Check if analytics is enabled
ANALYTICS_ENABLED = analytics_db is not None

if not ANALYTICS_ENABLED:
    print("⚠️  Analytics routes registered but analytics is disabled")


# ============================================
# DASHBOARD SUMMARY
# ============================================

@router.get("/summary")
async def get_analytics_summary(
        hours: int = Query(24, ge=1, le=168, description="Time range in hours (1-168)"),
        widget_type: Optional[str] = Query(None, description="Filter by widget type")
):
    """
    Get analytics summary for dashboard

    **Time Ranges:**
    - 24 hours (default)
    - 168 hours (7 days)

    **Widget Types:**
    - `default` - Standard widget
    - `auth` - Authenticated widget
    - `null` - All widgets (default)
    """
    if not ANALYTICS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Analytics is disabled. Enable it in config.yaml (analytics.enabled: true)"
        )

    try:
        summary = analytics_db.get_analytics_summary(
            hours=hours,
            widget_type=widget_type
        )
        return summary
    except Exception as e:
        print(f"❌ Analytics summary error: {e}")
        import traceback
        traceback.print_exc()
        raise server_error(e)


# ============================================
# TIME SERIES DATA
# ============================================

@router.get("/hourly-stats")
async def get_hourly_statistics(
        hours: int = Query(24, ge=1, le=168, description="Time range in hours")
):
    """
    Get hourly query statistics for charts

    **Returns:**
```json
    [
      {
        "hour": "2025-01-11 14:00:00",
        "total": 45,
        "successful": 42,
        "avg_time": 320.5
      }
    ]
```
    """
    if not ANALYTICS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Analytics is disabled. Enable it in config.yaml"
        )

    try:
        stats = analytics_db.get_hourly_stats(hours=hours)
        return stats
    except Exception as e:
        print(f"❌ Hourly stats error: {e}")
        import traceback
        traceback.print_exc()
        raise server_error(e)


# ============================================
# ERROR ANALYSIS
# ============================================

@router.get("/errors")
async def get_error_breakdown(
        hours: int = Query(24, ge=1, le=168, description="Time range in hours")
):
    """
    Get error types breakdown

    **Returns:**
```json
    {
      "period_hours": 24,
      "total_errors": 12,
      "error_types": [
        {"error": "Connection timeout", "count": 8},
        {"error": "SQL syntax error", "count": 4}
      ]
    }
```
    """
    if not ANALYTICS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Analytics is disabled. Enable it in config.yaml"
        )

    try:
        errors = analytics_db.get_error_breakdown(hours=hours)
        return {
            "period_hours": hours,
            "total_errors": sum(e['count'] for e in errors),
            "error_types": errors
        }
    except Exception as e:
        print(f"❌ Error breakdown error: {e}")
        import traceback
        traceback.print_exc()
        raise server_error(e)


# ============================================
# WIDGET COMPARISON
# ============================================

@router.get("/widget-comparison")
async def get_widget_comparison(
        hours: int = Query(24, ge=1, le=168, description="Time range in hours")
):
    """
    Compare default vs auth widget performance

    **Returns:**
```json
    {
      "period_hours": 24,
      "default": {
        "total_queries": 856,
        "success_rate": 95.2,
        "avg_time_ms": 310.5,
        "unique_sessions": 18
      },
      "auth": {
        "total_queries": 391,
        "success_rate": 92.1,
        "avg_time_ms": 420.3,
        "unique_sessions": 12,
        "unique_users": 8
      }
    }
```
    """
    if not ANALYTICS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Analytics is disabled. Enable it in config.yaml"
        )

    try:
        # Get stats for each widget type
        default_stats = analytics_db.get_analytics_summary(
            hours=hours,
            widget_type="default"
        )

        auth_stats = analytics_db.get_analytics_summary(
            hours=hours,
            widget_type="auth"
        )

        return {
            "period_hours": hours,
            "default": {
                "total_queries": default_stats["total_queries"],
                "success_rate": default_stats["success_rate"],
                "avg_time_ms": default_stats["avg_execution_time_ms"],
                "unique_sessions": default_stats["unique_sessions"]
            },
            "auth": {
                "total_queries": auth_stats["total_queries"],
                "success_rate": auth_stats["success_rate"],
                "avg_time_ms": auth_stats["avg_execution_time_ms"],
                "unique_sessions": auth_stats["unique_sessions"],
                "unique_users": auth_stats["unique_users"]
            }
        }
    except Exception as e:
        print(f"❌ Widget comparison error: {e}")
        import traceback
        traceback.print_exc()
        raise server_error(e)


# ============================================
# PERFORMANCE METRICS
# ============================================

@router.get("/performance")
async def get_performance_metrics(
        hours: int = Query(24, ge=1, le=168, description="Time range in hours")
):
    """
    Get performance distribution metrics

    **Returns:**
```json
    {
      "response_time_buckets": {
        "0-100ms": 125,
        "100-500ms": 450,
        "500-1000ms": 89,
        "1000ms+": 23
      },
      "avg_time_ms": 342.5,
      "median_time_ms": 280.0,
      "p95_time_ms": 850.0,
      "p99_time_ms": 1200.0
    }
```
    """
    if not ANALYTICS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Analytics is disabled. Enable it in config.yaml"
        )

    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_iso = cutoff.isoformat()

        with analytics_db.get_connection() as conn:
            with conn.cursor() as cursor:
                # Get all execution times for successful queries
                cursor.execute("""
                    SELECT execution_time_ms
                    FROM queries
                    WHERE created_at >= %s AND success = TRUE
                    ORDER BY execution_time_ms
                """, [cutoff_iso])

                times = [row['execution_time_ms'] for row in cursor.fetchall()]

                if not times:
                    return {
                        "response_time_buckets": {},
                        "avg_time_ms": 0,
                        "median_time_ms": 0,
                        "p95_time_ms": 0,
                        "p99_time_ms": 0
                    }

                # Calculate buckets
                buckets = {
                    "0-100ms": sum(1 for t in times if t < 100),
                    "100-500ms": sum(1 for t in times if 100 <= t < 500),
                    "500-1000ms": sum(1 for t in times if 500 <= t < 1000),
                    "1000ms+": sum(1 for t in times if t >= 1000)
                }

                # Calculate percentiles
                def percentile(data, p):
                    if not data:
                        return 0
                    k = (len(data) - 1) * p / 100
                    f = int(k)
                    c = f + 1 if f < len(data) - 1 else f
                    return data[f] + (k - f) * (data[c] - data[f])

                return {
                    "response_time_buckets": buckets,
                    "avg_time_ms": round(sum(times) / len(times), 2),
                    "median_time_ms": round(percentile(times, 50), 2),
                    "p95_time_ms": round(percentile(times, 95), 2),
                    "p99_time_ms": round(percentile(times, 99), 2)
                }

    except Exception as e:
        print(f"❌ Performance metrics error: {e}")
        import traceback
        traceback.print_exc()
        raise server_error(e)


# ============================================
# TOP USERS (AUTH WIDGET)
# ============================================

@router.get("/top-users")
async def get_top_users(
        hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
        limit: int = Query(10, ge=1, le=50, description="Number of users to return")
):
    """
    Get top users by query count (auth widget only)

    **Returns:**
```json
    [
      {
        "user_id": "osman.uygar",
        "query_count": 156,
        "success_rate": 94.2,
        "avg_time_ms": 320.5
      }
    ]
```
    """
    if not ANALYTICS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Analytics is disabled. Enable it in config.yaml"
        )

    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_iso = cutoff.isoformat()

        with analytics_db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        user_id,
                        COUNT(*) as query_count,
                        SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) as successful,
                        AVG(CASE WHEN success = TRUE THEN execution_time_ms ELSE NULL END) as avg_time
                    FROM queries
                    WHERE created_at >= %s 
                      AND widget_type = 'auth'
                      AND user_id IS NOT NULL
                    GROUP BY user_id
                    ORDER BY query_count DESC
                    LIMIT %s
                """, [cutoff_iso, limit])

                users = []
                for row in cursor.fetchall():
                    total = int(row['query_count']) if row['query_count'] else 0
                    successful = int(row['successful']) if row['successful'] else 0
                    users.append({
                        "user_id": row['user_id'],
                        "query_count": total,
                        "success_rate": round((successful / total * 100) if total > 0 else 0, 2),
                        "avg_time_ms": round(float(row['avg_time']) if row['avg_time'] else 0, 2)
                    })

                return users

    except Exception as e:
        print(f"❌ Top users error: {e}")
        import traceback
        traceback.print_exc()
        raise server_error(e)


# ============================================
# QUERY COMPLEXITY ANALYSIS
# ============================================

@router.get("/query-complexity")
async def get_query_complexity(
        hours: int = Query(24, ge=1, le=168, description="Time range in hours")
):
    """
    Analyze query complexity based on SQL patterns

    **Returns:**
```json
    {
      "period_hours": 24,
      "total_queries": 675,
      "complexity_breakdown": {
        "simple": 450,
        "medium": 180,
        "complex": 45
      },
      "complexity_percentages": {
        "simple": 66.67,
        "medium": 26.67,
        "complex": 6.67
      }
    }
```

    **Classification:**
    - Simple: No JOINs, basic SELECT
    - Medium: 1-2 JOINs, WHERE clauses
    - Complex: 3+ JOINs, subqueries, aggregations
    """
    if not ANALYTICS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Analytics is disabled. Enable it in config.yaml"
        )

    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_iso = cutoff.isoformat()

        with analytics_db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT sql
                    FROM queries
                    WHERE created_at >= %s AND success = TRUE
                """, [cutoff_iso])

                simple = 0
                medium = 0
                complex_count = 0

                for row in cursor.fetchall():
                    sql_upper = row['sql'].upper()

                    # Count JOINs
                    join_count = sql_upper.count(' JOIN ')

                    # Check for complex patterns
                    has_subquery = '(' in sql_upper and 'SELECT' in sql_upper.split('(', 1)[1]
                    has_group_by = 'GROUP BY' in sql_upper
                    has_having = 'HAVING' in sql_upper

                    if join_count >= 3 or has_subquery or (has_group_by and has_having):
                        complex_count += 1
                    elif join_count >= 1 or has_group_by:
                        medium += 1
                    else:
                        simple += 1

                total = simple + medium + complex_count

                return {
                    "period_hours": hours,
                    "total_queries": total,
                    "complexity_breakdown": {
                        "simple": simple,
                        "medium": medium,
                        "complex": complex_count
                    },
                    "complexity_percentages": {
                        "simple": round((simple / total * 100) if total > 0 else 0, 2),
                        "medium": round((medium / total * 100) if total > 0 else 0, 2),
                        "complex": round((complex_count / total * 100) if total > 0 else 0, 2)
                    }
                }

    except Exception as e:
        print(f"❌ Query complexity error: {e}")
        import traceback
        traceback.print_exc()
        raise server_error(e)


# ============================================
# HEALTH CHECK
# ============================================

@router.get("/health")
async def analytics_health_check():
    """
    Health check for analytics system

    **Returns:**
```json
    {
      "status": "healthy",
      "database": "connected",
      "backend": "postgresql",
      "total_queries_stored": 1247,
      "oldest_query": "2025-01-10T14:30:00",
      "newest_query": "2025-01-11T15:45:00"
    }
```
    """
    if not ANALYTICS_ENABLED:
        return {
            "status": "disabled",
            "database": "not_configured",
            "backend": "none",
            "message": "Analytics is disabled in config.yaml. Set analytics.enabled: true to enable."
        }

    try:
        with analytics_db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        MIN(created_at) as oldest,
                        MAX(created_at) as newest
                    FROM queries
                """)
                row = cursor.fetchone()

                return {
                    "status": "healthy",
                    "database": "connected",
                    "backend": "postgresql",
                    "total_queries_stored": row['total'] if row else 0,
                    "oldest_query": row['oldest'].isoformat() if row and row['oldest'] else None,
                    "newest_query": row['newest'].isoformat() if row and row['newest'] else None
                }

    except Exception as e:
        print(f"❌ Health check error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "unhealthy",
            "database": "error",
            "backend": "postgresql",
            "error": str(e)
        }


print("✅ Analytics routes registered")