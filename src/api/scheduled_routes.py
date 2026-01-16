# src/api/scheduled_routes.py
"""
API routes for scheduled queries
"""

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class ScheduleCreateRequest(BaseModel):
    """Request model for creating a schedule"""
    query_id: str = Field(..., description="ID of the favorite query to schedule")
    name: str = Field(..., min_length=1, max_length=255, description="Schedule name")
    description: Optional[str] = Field(None, description="Schedule description")

    frequency: str = Field(..., description="Frequency: daily, weekly, monthly, custom")
    cron_expression: str = Field(..., description="Cron expression")
    timezone: str = Field(default="UTC", description="Timezone for schedule")

    email_recipients: List[str] = Field(..., min_items=1, description="Email recipients")
    email_subject: Optional[str] = Field(None, description="Email subject template")
    email_body: Optional[str] = Field(None, description="Custom email body")
    format: str = Field(default="excel", description="Output format: csv, excel, html")

    enabled: bool = Field(default=True, description="Whether schedule is enabled")

    @validator('frequency')
    def validate_frequency(cls, v):
        if v not in ['daily', 'weekly', 'monthly', 'custom']:
            raise ValueError('Frequency must be: daily, weekly, monthly, or custom')
        return v

    @validator('format')
    def validate_format(cls, v):
        if v not in ['csv', 'excel', 'html', 'pdf']:
            raise ValueError('Format must be: csv, excel, html, or pdf')
        return v

    @validator('email_recipients')
    def validate_emails(cls, v):
        # Basic email validation
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        for email in v:
            if not re.match(email_pattern, email):
                raise ValueError(f'Invalid email: {email}')
        return v


class ScheduleUpdateRequest(BaseModel):
    """Request model for updating a schedule"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None

    frequency: Optional[str] = None
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None

    email_recipients: Optional[List[str]] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    format: Optional[str] = None

    enabled: Optional[bool] = None


class ScheduleResponse(BaseModel):
    """Response model for schedule"""
    id: str
    user_id: str
    query_id: str
    name: str
    description: Optional[str]

    frequency: str
    cron_expression: str
    timezone: str

    email_recipients: List[str]
    email_subject: Optional[str]
    email_body: Optional[str]
    format: str

    enabled: bool
    last_run: Optional[str]
    next_run: Optional[str]
    run_count: int

    created_at: str
    updated_at: str


class ExecutionResponse(BaseModel):
    """Response model for execution"""
    id: str
    schedule_id: str
    status: str
    started_at: str
    completed_at: Optional[str]
    duration_ms: Optional[int]
    rows_returned: Optional[int]
    error_message: Optional[str]


# ============================================
# DEPENDENCY INJECTION
# ============================================

# Global instances (set by app.py on startup)
schedules_db = None
scheduler_manager = None
query_history_manager = None


def get_current_user_id(x_session_id: Optional[str] = Header(None)) -> str:
    """
    Get current user ID from session
    Supports both auth plugin and standard widget
    """
    # Try to get user from auth plugin session
    if x_session_id:
        try:
            from src.plugins.auth_plugin import auth_plugin

            if auth_plugin and hasattr(auth_plugin, 'get_session'):
                session = auth_plugin.get_session(x_session_id)
                if session:
                    user_id = session.get('username') or session.get('user_id')
                    if user_id:
                        logger.info(f"📅 User authenticated: {user_id}")
                        return user_id
        except ImportError:
            pass  # Auth plugin not available
        except Exception as e:
            logger.warning(f"Failed to get user from auth plugin: {e}")

    # Fallback: default user (for standard widget or unauthenticated)
    return "default_user"


# ============================================
# ROUTES
# ============================================

@router.post("", response_model=ScheduleResponse)
async def create_schedule(
        request: ScheduleCreateRequest,
        user_id: str = Depends(get_current_user_id)
):
    """
    Create a new scheduled query
    """
    try:
        # Validate cron expression
        from apscheduler.triggers.cron import CronTrigger
        try:
            CronTrigger.from_crontab(request.cron_expression)
        except Exception as e:
            raise HTTPException(400, f"Invalid cron expression: {str(e)}")

        # Validate query exists in favorites
        # TODO: Check if query_id exists in user's favorites

        # Create schedule
        schedule_data = request.dict()
        schedule_data['user_id'] = user_id

        schedule = await schedules_db.create_schedule(schedule_data)

        # Add to scheduler
        if schedule['enabled']:
            scheduler_manager.add_scheduled_job(schedule)

        logger.info(f"✅ Created schedule: {schedule['name']}")

        return ScheduleResponse(**schedule)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to create schedule: {e}")
        raise HTTPException(500, f"Failed to create schedule: {str(e)}")


@router.get("", response_model=List[ScheduleResponse])
async def list_schedules(
        enabled: Optional[bool] = None,
        user_id: str = Depends(get_current_user_id)
):
    """
    Get all schedules for current user
    """
    try:
        schedules = await schedules_db.get_schedules(user_id, enabled)

        # Enrich with job info from scheduler
        for schedule in schedules:
            job_info = scheduler_manager.get_job_info(schedule['id'])
            if job_info:
                schedule['next_run'] = job_info['next_run_time']

        return [ScheduleResponse(**s) for s in schedules]

    except Exception as e:
        logger.error(f"❌ Failed to list schedules: {e}")
        raise HTTPException(500, f"Failed to list schedules: {str(e)}")


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
        schedule_id: str,
        user_id: str = Depends(get_current_user_id)
):
    """
    Get a specific schedule
    """
    try:
        schedule = await schedules_db.get_schedule(schedule_id)

        if not schedule:
            raise HTTPException(404, "Schedule not found")

        if schedule['user_id'] != user_id:
            raise HTTPException(403, "Not authorized to access this schedule")

        # Enrich with job info
        job_info = scheduler_manager.get_job_info(schedule_id)
        if job_info:
            schedule['next_run'] = job_info['next_run_time']

        return ScheduleResponse(**schedule)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get schedule: {e}")
        raise HTTPException(500, f"Failed to get schedule: {str(e)}")


@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
        schedule_id: str,
        request: ScheduleUpdateRequest,
        user_id: str = Depends(get_current_user_id)
):
    """
    Update a schedule
    """
    try:
        # Get existing schedule
        schedule = await schedules_db.get_schedule(schedule_id)

        if not schedule:
            raise HTTPException(404, "Schedule not found")

        if schedule['user_id'] != user_id:
            raise HTTPException(403, "Not authorized to update this schedule")

        # Validate cron if provided
        if request.cron_expression:
            from apscheduler.triggers.cron import CronTrigger
            try:
                CronTrigger.from_crontab(request.cron_expression)
            except Exception as e:
                raise HTTPException(400, f"Invalid cron expression: {str(e)}")

        # Update schedule
        updates = {k: v for k, v in request.dict().items() if v is not None}
        updated_schedule = await schedules_db.update_schedule(schedule_id, updates)

        # Update scheduler if enabled
        if updated_schedule['enabled']:
            scheduler_manager.add_scheduled_job(updated_schedule)
        else:
            scheduler_manager.remove_job(schedule_id)

        logger.info(f"✅ Updated schedule: {schedule_id}")

        return ScheduleResponse(**updated_schedule)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to update schedule: {e}")
        raise HTTPException(500, f"Failed to update schedule: {str(e)}")


@router.post("/{schedule_id}/toggle")
async def toggle_schedule(
        schedule_id: str,
        user_id: str = Depends(get_current_user_id)
):
    """
    Pause or resume a schedule
    """
    try:
        schedule = await schedules_db.get_schedule(schedule_id)

        if not schedule:
            raise HTTPException(404, "Schedule not found")

        if schedule['user_id'] != user_id:
            raise HTTPException(403, "Not authorized")

        # Toggle enabled status
        new_status = not schedule['enabled']
        await schedules_db.update_schedule(schedule_id, {'enabled': new_status})

        # Update scheduler
        if new_status:
            updated = await schedules_db.get_schedule(schedule_id)
            scheduler_manager.add_scheduled_job(updated)
            logger.info(f"▶️  Resumed schedule: {schedule_id}")
        else:
            scheduler_manager.remove_job(schedule_id)
            logger.info(f"⏸️  Paused schedule: {schedule_id}")

        return {
            'id': schedule_id,
            'enabled': new_status,
            'message': 'Resumed' if new_status else 'Paused'
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to toggle schedule: {e}")
        raise HTTPException(500, f"Failed to toggle schedule: {str(e)}")


@router.post("/{schedule_id}/run")
async def run_schedule_now(
        schedule_id: str,
        user_id: str = Depends(get_current_user_id)
):
    """
    Manually execute a schedule immediately
    """
    try:
        schedule = await schedules_db.get_schedule(schedule_id)

        if not schedule:
            raise HTTPException(404, "Schedule not found")

        if schedule['user_id'] != user_id:
            raise HTTPException(403, "Not authorized")

        # Execute in background
        import asyncio
        asyncio.create_task(scheduler_manager.execute_now(schedule_id))

        logger.info(f"▶️  Manual execution started: {schedule_id}")

        return {
            'id': schedule_id,
            'message': 'Execution started',
            'status': 'running'
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to run schedule: {e}")
        raise HTTPException(500, f"Failed to run schedule: {str(e)}")


@router.delete("/{schedule_id}")
async def delete_schedule(
        schedule_id: str,
        user_id: str = Depends(get_current_user_id)
):
    """
    Delete a schedule
    """
    try:
        schedule = await schedules_db.get_schedule(schedule_id)

        if not schedule:
            raise HTTPException(404, "Schedule not found")

        if schedule['user_id'] != user_id:
            raise HTTPException(403, "Not authorized")

        # Remove from scheduler
        scheduler_manager.remove_job(schedule_id)

        # Delete from database
        await schedules_db.delete_schedule(schedule_id)

        logger.info(f"🗑️  Deleted schedule: {schedule_id}")

        return {
            'id': schedule_id,
            'message': 'Schedule deleted'
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to delete schedule: {e}")
        raise HTTPException(500, f"Failed to delete schedule: {str(e)}")


@router.get("/{schedule_id}/executions", response_model=List[ExecutionResponse])
async def get_execution_history(
        schedule_id: str,
        limit: int = 50,
        user_id: str = Depends(get_current_user_id)
):
    """
    Get execution history for a schedule
    """
    try:
        schedule = await schedules_db.get_schedule(schedule_id)

        if not schedule:
            raise HTTPException(404, "Schedule not found")

        if schedule['user_id'] != user_id:
            raise HTTPException(403, "Not authorized")

        executions = await schedules_db.get_executions(schedule_id, limit)

        return [ExecutionResponse(**e) for e in executions]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get execution history: {e}")
        raise HTTPException(500, f"Failed to get execution history: {str(e)}")


@router.get("/{schedule_id}/stats")
async def get_schedule_stats(
        schedule_id: str,
        user_id: str = Depends(get_current_user_id)
):
    """
    Get execution statistics for a schedule
    """
    try:
        schedule = await schedules_db.get_schedule(schedule_id)

        if not schedule:
            raise HTTPException(404, "Schedule not found")

        if schedule['user_id'] != user_id:
            raise HTTPException(403, "Not authorized")

        stats = await schedules_db.get_execution_stats(schedule_id)

        return {
            'schedule_id': schedule_id,
            'schedule_name': schedule['name'],
            **stats
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get stats: {e}")
        raise HTTPException(500, f"Failed to get stats: {str(e)}")