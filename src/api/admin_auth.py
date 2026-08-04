import os
import secrets
import hashlib
import time
import logging
import threading
from collections import defaultdict
from typing import Optional
from fastapi import Depends, HTTPException, Request, status, Cookie
from fastapi.responses import RedirectResponse, HTMLResponse

logger = logging.getLogger(__name__)

# ── In-memory session store ──────────────────────────────────────
# { token: { "user": str, "expires_at": float } }
_sessions: dict[str, dict] = {}

# ── Admin login brute-force protection ──────────────────────────
# Mirrors the same pattern used in auth_plugin.py for /auth/login.
_ADMIN_MAX_ATTEMPTS = 10
_ADMIN_WINDOW_SEC   = 300   # 5 min rolling window
_ADMIN_LOCKOUT_SEC  = 600   # 10 min lockout

_admin_attempts: dict[str, list] = defaultdict(list)
_admin_lockouts: dict[str, float] = {}
_admin_lock = threading.Lock()


def _admin_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host or "unknown")


def _check_admin_login_allowed(ip: str) -> None:
    now = time.time()
    with _admin_lock:
        unlock_at = _admin_lockouts.get(ip, 0)
        if unlock_at > now:
            remaining = int(unlock_at - now)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed login attempts. Try again in {remaining}s.",
                headers={"Retry-After": str(remaining)},
            )
        _admin_attempts[ip] = [t for t in _admin_attempts[ip] if now - t < _ADMIN_WINDOW_SEC]


def _record_admin_failed_login(ip: str) -> None:
    now = time.time()
    with _admin_lock:
        _admin_attempts[ip].append(now)
        if len(_admin_attempts[ip]) >= _ADMIN_MAX_ATTEMPTS:
            _admin_lockouts[ip] = now + _ADMIN_LOCKOUT_SEC
            _admin_attempts[ip].clear()
            logger.warning("Admin login locked out for IP %s after %d failures", ip, _ADMIN_MAX_ATTEMPTS)


def _clear_admin_login_attempts(ip: str) -> None:
    with _admin_lock:
        _admin_attempts.pop(ip, None)
        _admin_lockouts.pop(ip, None)


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

    # Optional LDAP check first. Falls through to the local password on any
    # LDAP failure (bad credentials, misconfiguration, or an unreachable
    # server) so a directory outage never locks admins out entirely.
    from src.core.ldap_auth import authenticate as ldap_authenticate, is_enabled as ldap_enabled
    if ldap_enabled() and ldap_authenticate(username, password):
        return True

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


# ── FastAPI dependencies ─────────────────────────────────────────

def require_admin(
    request: Request,
    sqlatte_admin: Optional[str] = Cookie(default=None)
) -> str:
    """
    FastAPI dependency for HTML page routes — redirects browsers to login.
    Do NOT use on JSON/API routes; use require_admin_api there instead.
    """
    user = validate_session(sqlatte_admin)
    if user:
        return user

    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": f"/admin/login?next={request.url.path}"}
    )


def require_admin_api(
    sqlatte_admin: Optional[str] = Cookie(default=None)
) -> str:
    """
    FastAPI dependency for JSON API routes — returns 401 JSON instead of a browser redirect.
    This prevents fetch() callers from receiving an HTML page they'd try to parse as JSON.
    """
    user = validate_session(sqlatte_admin)
    if user:
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin authentication required",
        headers={"WWW-Authenticate": "Cookie"},
    )