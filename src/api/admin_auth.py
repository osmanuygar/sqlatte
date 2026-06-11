import os
import secrets
import hashlib
import time
import logging
from typing import Optional
from fastapi import Depends, HTTPException, Request, status, Cookie
from fastapi.responses import RedirectResponse, HTMLResponse

logger = logging.getLogger(__name__)

# ── In-memory session store ──────────────────────────────────────
# { token: { "user": str, "expires_at": float } }
_sessions: dict[str, dict] = {}


def _get_admin_config() -> dict:
    from src.core.config_manager_enhanced import config_manager
    config = config_manager.get_config()
    return config.get("admin", {})


def _session_ttl() -> int:
    cfg = _get_admin_config()
    minutes = cfg.get("session_ttl_minutes", 480)
    return int(minutes) * 60


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "user": username,
        "expires_at": time.time() + _session_ttl()
    }
    _cleanup_sessions()
    return token


def _cleanup_sessions():
    now = time.time()
    expired = [t for t, s in _sessions.items() if s["expires_at"] < now]
    for t in expired:
        del _sessions[t]


def validate_session(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    session = _sessions.get(token)
    if not session:
        return None
    if session["expires_at"] < time.time():
        del _sessions[token]
        return None
    return session["user"]


def destroy_session(token: str):
    _sessions.pop(token, None)


# ── Credentials verification ────────────────────────────────────

def verify_credentials(username: str, password: str) -> bool:

    cfg = _get_admin_config()

    if not cfg.get("enabled", True):
        # Auth disabled path removed — fail-closed to prevent accidental open access.
        # Set admin.enabled: true and admin.password in config.yaml.
        logger.error(
            "SECURITY: admin.enabled=false but auth bypass is disabled. "
            "Set admin.enabled: true and configure admin.username/password."
        )
        return False

    expected_user = cfg.get("username", "admin")
    expected_pass = cfg.get("password", "")

    # Refuse to operate with an empty password — fail-closed
    if not expected_pass:
        logger.error(
            "SECURITY: Admin password is not configured. "
            "Set admin.password in config.yaml or ADMIN_PASSWORD env var."
        )
        return False

    user_ok = secrets.compare_digest(username.encode(), expected_user.encode())
    pass_ok  = secrets.compare_digest(password.encode(), expected_pass.encode())

    return user_ok and pass_ok


# ── FastAPI dependency ───────────────────────────────────────────

def require_admin(
    request: Request,
    sqlatte_admin: Optional[str] = Cookie(default=None)
) -> str:
    """
    FastAPI dependency. /admin/* route'larına Depends(require_admin) ekle.

    """
    user = validate_session(sqlatte_admin)
    if user:
        return user

    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": f"/admin/login?next={request.url.path}"}
    )