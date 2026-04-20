"""
Alarm Routes – BigQuery Ops cost threshold alarms
"""

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/ops-agent/alarms", tags=["Ops Alarms"])

# Set by app.py after scheduler is initialized
scheduler_manager = None


# ──────────────────────────────────────────────────────
# REQUEST MODELS
# ──────────────────────────────────────────────────────

class AlarmConditionModel(BaseModel):
    field: str = "total_tb_processed"
    operator: str = "gt"
    threshold: float = 0.5


class AlarmNotificationsModel(BaseModel):
    email: bool = True
    jira: bool = False


class CreateAlarmRequest(BaseModel):
    name: str
    operation: str = "get_expensive_queries"
    params: Optional[Dict[str, Any]] = {"days": 1}
    condition: AlarmConditionModel
    notifications: AlarmNotificationsModel = AlarmNotificationsModel()
    schedule: str = "0 8 * * *"
    recipients: List[str] = []
    project_id: Optional[str] = None
    enabled: bool = True


class UpdateAlarmRequest(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    schedule: Optional[str] = None
    recipients: Optional[List[str]] = None
    condition: Optional[AlarmConditionModel] = None
    notifications: Optional[AlarmNotificationsModel] = None
    params: Optional[Dict[str, Any]] = None
    project_id: Optional[str] = None


# ──────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────

def _svc():
    from src.core.alarm_service import get_alarm_service
    svc = get_alarm_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Alarm service not initialized")
    return svc


def _schedule_alarm(alarm, svc):
    """Register or re-register an alarm job in APScheduler."""
    if not scheduler_manager:
        return
    try:
        from apscheduler.triggers.cron import CronTrigger
        tz = getattr(scheduler_manager, 'default_timezone', 'UTC')
        scheduler_manager.scheduler.add_job(
            func=svc.evaluate_alarm,
            trigger=CronTrigger.from_crontab(alarm.schedule, timezone=tz),
            args=[alarm],
            id=f"alarm_{alarm.id}",
            replace_existing=True,
            name=f"alarm:{alarm.name}",
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not schedule alarm '{alarm.name}': {e}")


def _unschedule_alarm(alarm_id: str):
    """Remove an alarm job from APScheduler if it exists."""
    if not scheduler_manager:
        return
    try:
        scheduler_manager.scheduler.remove_job(f"alarm_{alarm_id}")
    except Exception:
        pass


def _get_job_info(alarm_id: str) -> Dict:
    """Return next_run_time for an alarm job."""
    if not scheduler_manager:
        return {}
    try:
        job = scheduler_manager.scheduler.get_job(f"alarm_{alarm_id}")
        if job and job.next_run_time:
            return {"next_run": job.next_run_time.isoformat(), "scheduled": True}
    except Exception:
        pass
    return {"next_run": None, "scheduled": False}


# ──────────────────────────────────────────────────────
# JIRA CONFIG ENDPOINT
# ──────────────────────────────────────────────────────

@router.get("/jira-config")
async def get_jira_config():
    """Return Jira configuration status (no secrets exposed)."""
    from src.core.alarm_service import get_alarm_service
    svc = get_alarm_service()
    if not svc:
        return {"enabled": False, "configured": False}
    cfg = svc.jira_config
    return {
        "enabled": cfg.get("enabled", False),
        "configured": bool(cfg.get("url") and cfg.get("email") and cfg.get("api_token") and cfg.get("project_key")),
        "url": cfg.get("url", ""),
        "email": cfg.get("email", ""),
        "project_key": cfg.get("project_key", ""),
        "issue_type": cfg.get("issue_type", "Bug"),
        "priority": cfg.get("priority", "High"),
    }


@router.get("/jira-issue-types")
async def get_jira_issue_types():
    """Return valid issue types for the configured Jira project."""
    import urllib.request, urllib.error, json
    from src.core.alarm_service import get_alarm_service
    svc = get_alarm_service()
    if not svc:
        return {"error": "Alarm service not initialized"}
    cfg = svc.jira_config
    url = cfg.get("url", "").rstrip("/")
    api_token = cfg.get("api_token", "")
    project_key = cfg.get("project_key", "")
    if not all([url, api_token, project_key]):
        return {"error": "Jira config incomplete"}
    req = urllib.request.Request(
        f"{url}/rest/api/2/project/{project_key}",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {"issue_types": [{"id": it["id"], "name": it["name"]} for it in data.get("issueTypes", [])]}
    except urllib.error.HTTPError as e:
        return {"error": f"{e.code}: {e.read().decode(errors='replace')}"}


# ──────────────────────────────────────────────────────
# ALARM CRUD
# ──────────────────────────────────────────────────────

@router.get("")
async def list_alarms():
    from src.core.alarm_service import get_alarm_service
    svc = get_alarm_service()
    if not svc:
        return {"alarms": []}
    alarms = svc.get_alarms()
    for a in alarms:
        a.update(_get_job_info(a["id"]))
    return {"alarms": alarms}


@router.post("")
async def create_alarm(req: CreateAlarmRequest):
    svc = _svc()
    alarm = svc.create_alarm(
        name=req.name,
        operation=req.operation,
        params=req.params or {},
        condition=req.condition.dict(),
        notifications=req.notifications.dict(),
        schedule=req.schedule,
        recipients=req.recipients,
        project_id=req.project_id,
        enabled=req.enabled,
    )
    if alarm.enabled:
        _schedule_alarm(alarm, svc)
    return {"success": True, "alarm": asdict(alarm)}


@router.put("/{alarm_id}")
async def update_alarm(alarm_id: str, req: UpdateAlarmRequest):
    svc = _svc()
    updates = {k: v for k, v in req.dict().items() if v is not None}
    alarm = svc.update_alarm(alarm_id, updates)
    if not alarm:
        raise HTTPException(status_code=404, detail=f"Alarm '{alarm_id}' not found")
    if alarm.enabled:
        _schedule_alarm(alarm, svc)
    else:
        _unschedule_alarm(alarm_id)
    return {"success": True, "alarm": asdict(alarm)}


@router.delete("/{alarm_id}")
async def delete_alarm(alarm_id: str):
    svc = _svc()
    if not svc.delete_alarm(alarm_id):
        raise HTTPException(status_code=404, detail=f"Alarm '{alarm_id}' not found")
    _unschedule_alarm(alarm_id)
    return {"success": True}


@router.get("/history/all")
async def get_all_history(limit: int = 100):
    from src.core.alarm_service import get_alarm_service
    svc = get_alarm_service()
    return {"history": svc.get_alarm_history(limit=limit) if svc else []}


@router.post("/{alarm_id}/test")
async def test_alarm(alarm_id: str):
    svc = _svc()
    alarm = svc.alarms.get(alarm_id)
    if not alarm:
        raise HTTPException(status_code=404, detail=f"Alarm '{alarm_id}' not found")
    result = await svc.evaluate_alarm(alarm)
    return {"success": True, "result": result}


@router.get("/{alarm_id}/history")
async def get_alarm_history(alarm_id: str, limit: int = 50):
    from src.core.alarm_service import get_alarm_service
    svc = get_alarm_service()
    return {"history": svc.get_alarm_history(alarm_id, limit) if svc else []}
