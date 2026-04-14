"""
BigQuery Ops Agent API Routes

Provides REST endpoints for operational playbook execution
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

router = APIRouter(prefix="/ops-agent", tags=["BigQuery Ops"])


class OpsExecuteRequest(BaseModel):
    """Request model for operation execution"""
    operation: str
    params: Optional[Dict[str, Any]] = None


# ═══════════════════════════════════════════════════
# OPERATIONS LISTING
# ═══════════════════════════════════════════════════

@router.get("/operations")
async def list_operations():
    """
    List all available operations

    Returns:
        {
            "agent": {
                "type": "bigquery_ops_agent",
                "project": "analytics-prod",
                ...
            },
            "operations": [
                {
                    "name": "get_expensive_queries",
                    "description": "...",
                    "category": "cost",
                    "params": [...],
                    "estimated_duration_sec": 5
                },
                ...
            ]
        }
    """
    # Import here to avoid circular dependencies
    from src.core.provider_factory import get_ops_agent

    ops_agent = get_ops_agent()

    if not ops_agent:
        return {
            "agent": None,
            "operations": [],
            "message": "BigQuery Ops Agent not configured in config.yaml"
        }

    return {
        "agent": ops_agent.get_connection_info(),
        "operations": ops_agent.get_available_operations()
    }


# ═══════════════════════════════════════════════════
# OPERATION EXECUTION
# ═══════════════════════════════════════════════════

@router.post("/execute")
async def execute_operation(request: OpsExecuteRequest):
    """
    Execute an operational playbook

    Request Body:
        {
            "operation": "get_expensive_queries",
            "params": {"days": 30}
        }

    Response:
        {
            "success": true,
            "operation": "get_expensive_queries",
            "data": [...],
            "summary": "...",
            "recommendations": [...],
            "visualization": {...},
            "row_count": 10
        }

    Raises:
        400: If ops agent not configured
        500: If operation execution fails
    """
    from src.core.provider_factory import get_ops_agent

    ops_agent = get_ops_agent()

    if not ops_agent:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "BigQuery Ops Agent not configured",
                "message": "Enable ops_agent in config.yaml to use this feature"
            }
        )

    try:
        result = await ops_agent.execute_operation(
            operation_name=request.operation,
            params=request.params
        )

        return result.to_dict()

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Operation execution failed",
                "message": str(e),
                "operation": request.operation
            }
        )


# ═══════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════

@router.get("/health")
async def health_check():
    """
    Check ops agent health and connectivity

    Returns:
        {
            "healthy": true,
            "project": "analytics-prod",
            "region": "US",
            "datasets_accessible": 150,
            "message": "Agent ready",
            "last_check": "2024-01-15T10:30:00Z"
        }
    """
    from src.core.provider_factory import get_ops_agent

    ops_agent = get_ops_agent()

    if not ops_agent:
        return {
            "healthy": False,
            "message": "BigQuery Ops Agent not configured in config.yaml",
            "hint": "Add ops_agent section to config.yaml and restart"
        }

    try:
        health_data = await ops_agent.health_check()
        return health_data

    except Exception as e:
        return {
            "healthy": False,
            "error": str(e),
            "message": "Health check failed"
        }