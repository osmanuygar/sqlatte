"""
Optional LDAP login gate for the SQLatte Assistant — the legacy /query
widget (frontend/index.html), which today has no login at all.

Disabled by default: enable with plugins.assistant_login.enabled AND
ldap.enabled in config.yaml. On success this does NOT connect with the
user's own database credentials — it's an identity check only. The issued
session carries the server's own `database` config, the same connection
/query already uses for every caller.
"""
import logging
import threading
import time
from collections import defaultdict
from typing import Dict

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel, field_validator

from src.core import ldap_auth
from src.core.config_manager_enhanced import config_manager
from src.plugins.session_manager import auth_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/assistant", tags=["assistant-auth"])


# ── Brute-force protection — mirrors admin_auth.py / auth_plugin.py ───────

_MAX_ATTEMPTS = 10
_WINDOW_SEC   = 300
_LOCKOUT_SEC  = 600

_attempts: Dict[str, list] = defaultdict(list)
_lockouts: Dict[str, float] = {}
_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host or "unknown")


def _check_login_allowed(ip: str) -> None:
    now = time.time()
    with _lock:
        unlock_at = _lockouts.get(ip, 0)
        if unlock_at > now:
            remaining = int(unlock_at - now)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed login attempts. Try again in {remaining}s.",
                headers={"Retry-After": str(remaining)},
            )
        _attempts[ip] = [t for t in _attempts[ip] if now - t < _WINDOW_SEC]


def _record_failed_login(ip: str) -> None:
    now = time.time()
    with _lock:
        _attempts[ip].append(now)
        if len(_attempts[ip]) >= _MAX_ATTEMPTS:
            _lockouts[ip] = now + _LOCKOUT_SEC
            _attempts[ip].clear()
            logger.warning("Assistant login locked out for IP %s after %d failures", ip, _MAX_ATTEMPTS)


def _clear_login_attempts(ip: str) -> None:
    with _lock:
        _attempts.pop(ip, None)
        _lockouts.pop(ip, None)


# ── Config helpers ─────────────────────────────────────────────────────

def _assistant_login_config() -> dict:
    return config_manager.get_config().get("plugins", {}).get("assistant_login", {})


def is_gate_enabled() -> bool:
    return bool(_assistant_login_config().get("enabled", False))


def _server_db_config() -> Dict[str, dict]:
    """Build a session db_config from the server's own `database` section —
    the same connection /query already uses for every (unauthenticated) caller."""
    db_section = config_manager.get_config().get("database", {})
    provider = db_section.get("provider", "")
    if not provider:
        raise HTTPException(500, "No database provider configured on server")
    provider_cfg = db_section.get(provider, {})
    if not provider_cfg:
        raise HTTPException(500, f"No config found for provider '{provider}'")
    return {"provider": provider, provider: provider_cfg}


# ── Request models ────────────────────────────────────────────────────

class AssistantLoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def validate_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field must not be empty")
        return v


# ── Routes ────────────────────────────────────────────────────────────

@router.get("/config")
async def assistant_login_config():
    """Tells the frontend whether to show the LDAP login gate."""
    return {"enabled": is_gate_enabled()}


@router.post("/login")
async def assistant_login(request: AssistantLoginRequest, http_request: Request):
    """LDAP-authenticate, then issue a session backed by the server's own
    database credentials. Identity check only — not a per-user DB login."""
    if not is_gate_enabled():
        raise HTTPException(403, "Assistant login is not enabled")

    if not ldap_auth.is_enabled():
        logger.error("SECURITY: plugins.assistant_login.enabled=true but ldap.enabled=false")
        raise HTTPException(500, "LDAP is not configured on the server")

    ip = _client_ip(http_request)
    _check_login_allowed(ip)

    canonical_username = ldap_auth.authenticate(request.username, request.password)
    if not canonical_username:
        _record_failed_login(ip)
        raise HTTPException(401, "Invalid LDAP credentials")

    _clear_login_attempts(ip)

    cfg = _assistant_login_config()
    ttl_minutes = int(float(cfg.get("ttl_hours", 8)) * 60)

    session_id = auth_session_manager.create_session(
        username=canonical_username,
        db_config=_server_db_config(),
        ttl_minutes=ttl_minutes,
    )

    return {
        "success": True,
        "session_id": session_id,
        "username": canonical_username,
        "ttl_minutes": ttl_minutes,
    }


@router.post("/logout")
async def assistant_logout(session_id: str = Header(..., alias="X-Session-ID")):
    success = auth_session_manager.destroy_session(session_id)
    if not success:
        raise HTTPException(404, "Session not found")
    return {"success": True, "message": "Logged out successfully"}
