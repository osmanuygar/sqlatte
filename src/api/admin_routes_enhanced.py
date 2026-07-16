import os
from fastapi import APIRouter, HTTPException, Request, Depends, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from src.core.config_manager_enhanced import config_manager
from src.core.error_utils import server_error
from src.api.admin_auth import (
    require_admin,
    verify_credentials,
    create_session,
    destroy_session,
    validate_session,
    _admin_client_ip,
    _check_admin_login_allowed,
    _record_admin_failed_login,
    _clear_admin_login_attempts,
)


def _secure_cookies() -> bool:
    """Return True when the server is running behind HTTPS or explicitly configured for it."""
    cfg = config_manager.get_config()
    return cfg.get("admin", {}).get("secure_cookies", os.environ.get("HTTPS", "").lower() in ("1", "true", "yes"))

router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================
# REQUEST MODELS
# ============================================

class ConfigUpdateRequest(BaseModel):
    """Request model for config updates"""
    updates: Dict[str, Any]
    persist: bool = False
    reason: Optional[str] = None


class LLMConfigRequest(BaseModel):
    """Request model for LLM config updates"""
    provider: str
    config: Dict[str, Any]
    persist: bool = False


class DatabaseConfigRequest(BaseModel):
    """Request model for Database config updates"""
    provider: str
    config: Dict[str, Any]
    persist: bool = False


class EmailConfigRequest(BaseModel):
    """Request model for Email config updates"""
    config: Dict[str, Any]
    persist: bool = False


class TestConnectionRequest(BaseModel):
    """Request model for testing provider connections"""
    provider_type: str  # 'llm' or 'database'
    provider: str
    config: Dict[str, Any]


class SnapshotRequest(BaseModel):
    """Request model for creating snapshots"""
    snapshot_name: str
    description: Optional[str] = None


class RestoreSnapshotRequest(BaseModel):
    """Request model for restoring snapshots"""
    snapshot_name: str


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(
    request: Request,
    sqlatte_admin: Optional[str] = Cookie(default=None)
):
    """Login sayfasını serve et. Zaten login'se /admin/'a redirect."""
    if validate_session(sqlatte_admin):
        return RedirectResponse("/admin/", status_code=302)

    login_html_path = os.path.join(
        os.path.dirname(__file__),
        "../../frontend/admin-login.html"
    )
    if os.path.exists(login_html_path):
        with open(login_html_path, "r") as f:
            return HTMLResponse(content=f.read())

    # Fallback: basit form (admin-login.html bulunamazsa)
    return HTMLResponse(content="""
        <html><body style="background:#0a0a0a;color:#e0e0e0;display:flex;
            align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
            <div style="background:#1e1e1e;border:1px solid #2a2a2a;border-radius:12px;padding:40px;width:360px">
                <h2 style="color:#D4A574;margin-bottom:24px">☕ SQLatte Admin</h2>
                <form method="post" action="/admin/login">
                    <input name="username" placeholder="Username"
                        style="width:100%;padding:10px;background:#141414;border:1px solid #333;
                        border-radius:8px;color:#fff;margin-bottom:12px"><br>
                    <input name="password" type="password" placeholder="Password"
                        style="width:100%;padding:10px;background:#141414;border:1px solid #333;
                        border-radius:8px;color:#fff;margin-bottom:16px"><br>
                    <button type="submit"
                        style="width:100%;padding:12px;background:#D4A574;border:none;
                        border-radius:8px;font-weight:700;cursor:pointer">Login →</button>
                </form>
            </div>
        </body></html>
    """)


@router.post("/login", include_in_schema=False)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = "/admin/"
):
    """
    Form POST → credentials doğrula → cookie set et → redirect.
    JavaScript fetch ile de çağrılabilir (JSON body değil Form data).
    """
    ip = _admin_client_ip(request)
    _check_admin_login_allowed(ip)

    if verify_credentials(username, password):
        _clear_admin_login_attempts(ip)
        token = create_session(username)
        response = RedirectResponse(next, status_code=302)
        response.set_cookie(
            key="sqlatte_admin",
            value=token,
            httponly=True,
            secure=_secure_cookies(),
            samesite="strict",
            max_age=_get_session_ttl_seconds()
        )
        return response

    _record_admin_failed_login(ip)
    return RedirectResponse("/admin/login?error=1", status_code=302)


@router.post("/login/json", include_in_schema=False)
async def login_json(request: Request):
    """
    JavaScript fetch için JSON endpoint.
    Body: { "username": "...", "password": "..." }
    Response: { "success": true/false }
    """
    ip = _admin_client_ip(request)
    _check_admin_login_allowed(ip)

    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")

    if verify_credentials(username, password):
        _clear_admin_login_attempts(ip)
        token = create_session(username)
        response = JSONResponse({"success": True})
        response.set_cookie(
            key="sqlatte_admin",
            value=token,
            httponly=True,
            secure=_secure_cookies(),
            samesite="strict",
            max_age=_get_session_ttl_seconds()
        )
        return response

    _record_admin_failed_login(ip)
    return JSONResponse(
        {"success": False, "detail": "Invalid credentials"},
        status_code=401
    )


@router.get("/logout", include_in_schema=False)
async def logout(sqlatte_admin: Optional[str] = Cookie(default=None)):
    """Session'ı yok et ve login sayfasına yönlendir."""
    if sqlatte_admin:
        destroy_session(sqlatte_admin)
    response = RedirectResponse("/admin/login", status_code=302)
    response.delete_cookie("sqlatte_admin")
    return response


def _get_session_ttl_seconds() -> int:
    """Cookie max_age için session TTL."""
    from src.api.admin_auth import _session_ttl
    return _session_ttl()

# ============================================
# ADMIN PAGE
# ============================================

@router.get("/", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    admin_user: str = Depends(require_admin)   # ← BU SATIRI EKLE
):
    """Serve admin configuration page"""
    admin_html_path = os.path.join(
        os.path.dirname(__file__),
        "../../frontend/admin.html"
    )

    if not os.path.exists(admin_html_path):
        return HTMLResponse(
            content="<h1>Admin page not found</h1>",
            status_code=404
        )

    with open(admin_html_path, "r") as f:
        content = f.read()

    # Admin header'a kullanıcı adı ve logout butonu inject et
    logout_snippet = f"""
    <script>
        // Inject logout button into admin header
        document.addEventListener('DOMContentLoaded', () => {{
            const actions = document.querySelector('.admin-actions');
            if (actions) {{
                const logoutBtn = document.createElement('a');
                logoutBtn.href = '/admin/logout';
                logoutBtn.className = 'btn btn-secondary';
                logoutBtn.innerHTML = '🚪 Logout ({admin_user})';
                logoutBtn.style.textDecoration = 'none';
                actions.prepend(logoutBtn);
            }}
        }});
    </script>
    """
    content = content.replace("</body>", logout_snippet + "\n</body>")
    return HTMLResponse(content=content)

# ============================================
# CONFIG MANAGEMENT
# ============================================

@router.get("/config")
async def get_current_config(admin_user: str = Depends(require_admin)):
    """
    Get current configuration (with sensitive data masked)
    """
    try:
        # Get config using proper priority: DB > Runtime > YAML
        safe_config = config_manager.get_safe_config()

        return {
            "success": True,
            "config": safe_config,
            "has_runtime_overrides": len(config_manager.runtime_overrides) > 0,
            "db_enabled": config_manager.db_enabled,
            "config_file": config_manager.config_path,
            # Debug info
            "debug": {
                "config_db_type": config_manager.config_db.db_type if config_manager.config_db else None,
                "total_db_configs": len(config_manager.config_db.get_all_configs()) if config_manager.config_db else 0,
                "has_email_config": 'email' in safe_config,
                "has_scheduler_config": 'scheduler' in safe_config,
                "has_insights_config": 'insights' in safe_config,
                "has_export_config": 'export' in safe_config,
            }
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise server_error(e)

@router.post("/config")
async def update_config(request: ConfigUpdateRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """
    Update configuration with optional persistence

    Example:
    ```json
    {
        "updates": {
            "llm": {
                "provider": "anthropic",
                "anthropic": {
                    "model": "claude-sonnet-4-20250514"
                }
            }
        },
        "persist": true,
        "reason": "Changed model to Sonnet 4"
    }
    ```
    """
    try:
        # Get user from session or use 'api'
        user = http_request.headers.get('X-User', 'api')
        client_ip = http_request.client.host if http_request.client else 'unknown'

        updated_config = config_manager.update_config(
            updates=request.updates,
            persist=request.persist,
            user=user,
            reason=request.reason
        )

        return {
            "success": True,
            "message": "Configuration updated" + (" and persisted" if request.persist else ""),
            "config": config_manager.get_safe_config()
        }
    except Exception as e:
        raise server_error(e)


@router.put("/config/llm")
async def update_llm_config(request: LLMConfigRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """
    Update LLM provider configuration

    Example:
    ```json
    {
        "provider": "anthropic",
        "config": {
            "model": "claude-sonnet-4-20250514",
            "temperature": 0.1,
            "api_key": "sk-ant-..."
        },
        "persist": true
    }
    ```
    """
    try:
        user = http_request.headers.get('X-User', 'api')

        updated_config = config_manager.update_llm_config(
            provider=request.provider,
            provider_config=request.config,
            persist=request.persist,
            user=user
        )

        return {
            "success": True,
            "message": f"LLM configuration updated: {request.provider}",
            "config": updated_config.get('llm', {})
        }
    except Exception as e:
        raise server_error(e)


@router.put("/config/database")
async def update_database_config(request: DatabaseConfigRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """
    Update Database provider configuration

    Example:
    ```json
    {
        "provider": "clickhouse",
        "config": {
            "host": "localhost",
            "port": 8123,
            "database": "default",
            "username": "default",
            "password": "password123"
        },
        "persist": true
    }
    ```
    """
    try:
        user = http_request.headers.get('X-User', 'api')

        updated_config = config_manager.update_database_config(
            provider=request.provider,
            provider_config=request.config,
            persist=request.persist,
            user=user
        )

        return {
            "success": True,
            "message": f"Database configuration updated: {request.provider}",
            "config": updated_config.get('database', {})
        }
    except Exception as e:
        raise server_error(e)


@router.put("/config/email")
async def update_email_config(request: EmailConfigRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """
    Update Email configuration

    Example:
    ```json
    {
        "config": {
            "enabled": true,
            "smtp": {
                "host": "smtp.gmail.com",
                "port": 587,
                "user": "user@gmail.com",
                "password": "app-password",
                "from_email": "noreply@example.com",
                "from_name": "SQLatte Reports"
            }
        },
        "persist": true
    }
    ```
    """
    try:
        user = http_request.headers.get('X-User', 'api')

        updated_config = config_manager.update_email_config(
            email_config=request.config,
            persist=request.persist,
            user=user
        )

        return {
            "success": True,
            "message": "Email configuration updated",
            "config": updated_config.get('email', {})
        }
    except Exception as e:
        raise server_error(e)


class SchedulerConfigRequest(BaseModel):
    """Request model for Scheduler config updates"""
    config: Dict[str, Any]
    persist: bool = False


@router.put("/config/scheduler")
async def update_scheduler_config(request: SchedulerConfigRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """
    Update Scheduler configuration

    Example:
    ```json
    {
        "config": {
            "enabled": true,
            "timezone": "UTC",
            "max_concurrent_jobs": 10,
            "job_timeout_seconds": 300,
            "keep_history_days": 30
        },
        "persist": true
    }
    ```
    """
    try:
        user = http_request.headers.get('X-User', 'api')

        # Update scheduler config
        updates = {'scheduler': request.config}
        config_manager.update_config(
            updates=updates,
            persist=request.persist,
            user=user,
            reason="Scheduler config updated"
        )

        return {
            "success": True,
            "message": "Scheduler configuration updated",
            "config": request.config
        }
    except Exception as e:
        raise server_error(e)


class InsightsConfigRequest(BaseModel):
    """Request model for Insights config updates"""
    config: Dict[str, Any]
    persist: bool = False


@router.put("/config/insights")
async def update_insights_config(request: InsightsConfigRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """Update Insights Engine configuration
    ✅ UPDATED: Now reloads insights engine on apply
    """
    try:
        user = http_request.headers.get('X-User', 'api')

        # Update config in DB
        updates = {'insights': request.config}
        config_manager.update_config(
            updates=updates,
            persist=request.persist,
            user=user,
            reason="Insights engine config updated"
        )

        # ✅ NEW: RELOAD ENGINE
        try:
            from src.core.llm_insights_engine import initialize_insights_engine
            import sys

            if 'app' in sys.modules:
                app_module = sys.modules['app']
                if hasattr(app_module, 'llm_provider'):
                    llm_provider = app_module.llm_provider

                    print(f"🔄 Reloading insights engine...")
                    initialize_insights_engine(
                        llm_provider=llm_provider,
                        enabled=request.config.get('enabled', False),
                        mode=request.config.get('mode', 'hybrid'),
                        max_insights=request.config.get('max_insights', 3)
                    )
                    print(f"✅ Insights engine reloaded (enabled={request.config.get('enabled')})")
        except Exception as reload_error:
            print(f"⚠️ Failed to reload: {reload_error}")

        return {
            "success": True,
            "message": "Insights configuration updated and engine reloaded",
            "config": request.config
        }
    except Exception as e:
        raise server_error(e)


class OpsAgentConfigRequest(BaseModel):
    """Request model for Ops Agent config updates"""
    config: Dict[str, Any]
    persist: bool = False


@router.put("/config/ops-agent")
async def update_ops_agent_config(request: OpsAgentConfigRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """Update Ops Agent configuration (enabled, ai_insights toggle, ai_insights_max)"""
    try:
        user = http_request.headers.get('X-User', 'api')

        # Merge only the editable keys — preserve provider, projects, allowed_operations etc.
        current = config_manager.get_config()
        existing = current.get('ops_agent', {})
        existing.update({
            'enabled': request.config.get('enabled', existing.get('enabled', True)),
            'ai_insights': request.config.get('ai_insights', existing.get('ai_insights', False)),
            'ai_insights_max': request.config.get('ai_insights_max', existing.get('ai_insights_max', 5)),
        })

        config_manager.update_config(
            updates={'ops_agent': existing},
            persist=request.persist,
            user=user,
            reason="Ops Agent config updated"
        )

        return {
            "success": True,
            "message": "Ops Agent configuration updated",
            "config": existing
        }
    except Exception as e:
        raise server_error(e)


class ExportConfigRequest(BaseModel):
    """Request model for Export config updates"""
    config: Dict[str, Any]
    persist: bool = False


@router.put("/config/export")
async def update_export_config(request: ExportConfigRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """
    Update Export configuration

    Example:
    ```json
    {
        "config": {
            "formats": ["csv", "excel", "html"],
            "max_rows": 1000,
            "max_file_size_mb": 25,
            "filename_template": "{{schedule_name}}_{{date}}.{{format}}"
        },
        "persist": true
    }
    ```
    """
    try:
        user = http_request.headers.get('X-User', 'api')

        # Update export config
        updates = {'export': request.config}
        config_manager.update_config(
            updates=updates,
            persist=request.persist,
            user=user,
            reason="Export config updated"
        )

        return {
            "success": True,
            "message": "Export configuration updated",
            "config": request.config
        }
    except Exception as e:
        raise server_error(e)


@router.post("/test/email")
async def test_email_connection(request: Dict[str, Any], admin_user: str = Depends(require_admin)):
    """
    Test SMTP email connection

    Example:
    ```json
    {
        "host": "smtp.gmail.com",
        "port": 587,
        "user": "user@gmail.com",
        "password": "app-password",
        "use_tls": true
    }
    ```
    """
    try:
        import smtplib
        from email.mime.text import MIMEText

        host = request.get('host')
        port = request.get('port', 587)
        user = request.get('user')
        password = request.get('password')
        use_tls = request.get('use_tls', True)

        # Test connection
        server = smtplib.SMTP(host, port, timeout=10)

        if use_tls:
            server.starttls()

        if user and password:
            server.login(user, password)

        server.quit()

        return {
            "success": True,
            "message": "SMTP connection successful"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"SMTP connection failed: {str(e)}"
        }


@router.put("/config/email")
async def update_email_config(request: EmailConfigRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """
    Update Email configuration

    Example:
    ```json
    {
        "config": {
            "enabled": true,
            "smtp": {
                "host": "smtp.gmail.com",
                "port": 587,
                "user": "user@gmail.com",
                "password": "app-password"
            }
        },
        "persist": true
    }
    ```
    """
    try:
        user = http_request.headers.get('X-User', 'api')

        updated_config = config_manager.update_email_config(
            email_config=request.config,
            persist=request.persist,
            user=user
        )

        return {
            "success": True,
            "message": "Email configuration updated",
            "config": updated_config.get('email', {})
        }
    except Exception as e:
        raise server_error(e)


@router.post("/config/reset")
async def reset_config(admin_user: str = Depends(require_admin)):
    """
    Reset configuration to file defaults (clear runtime overrides)
    """
    try:
        config = config_manager.reset_to_file()

        return {
            "success": True,
            "message": "Configuration reset to file defaults",
            "config": config_manager.get_safe_config()
        }
    except Exception as e:
        raise server_error(e)


@router.post("/config/migrate-analytics")
async def migrate_analytics_config(admin_user: str = Depends(require_admin)):
    """
    Backfill analytics.postgresql.* (including the encrypted password) into
    config_db for installs that were bootstrapped before analytics support
    was added to bootstrap_from_yaml. Safe to call repeatedly — no-ops if
    already migrated. Requires config_db to be enabled.
    """
    if not config_manager.config_db:
        raise HTTPException(status_code=400, detail="config_db is not enabled — nothing to migrate into")

    try:
        migrated = config_manager.config_db.migrate_analytics_config(config_manager.config)
        return {
            "success": True,
            "migrated": migrated,
            "message": "Analytics config migrated into config_db" if migrated
                       else "Already migrated — no changes made",
        }
    except Exception as e:
        raise server_error(e)


# ============================================
# CONFIG HISTORY & SNAPSHOTS
# ============================================

@router.get("/config/history")
async def get_config_history(key: Optional[str] = None, limit: int = 100, admin_user: str = Depends(require_admin)):
    """
    Get configuration change history

    Query params:
    - key: Filter by specific config key (optional)
    - limit: Maximum number of records (default 100)
    """
    try:
        history = config_manager.get_config_history(key=key, limit=limit)

        return {
            "success": True,
            "history": history,
            "count": len(history),
            "db_enabled": config_manager.db_enabled
        }
    except Exception as e:
        raise server_error(e)


@router.post("/config/snapshot")
async def create_snapshot(request: SnapshotRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """
    Create a configuration snapshot for rollback

    Example:
    ```json
    {
        "snapshot_name": "before_production_deploy",
        "description": "Snapshot before deploying to production"
    }
    ```
    """
    try:
        user = http_request.headers.get('X-User', 'api')

        success = config_manager.create_snapshot(
            snapshot_name=request.snapshot_name,
            user=user,
            description=request.description
        )

        if success:
            return {
                "success": True,
                "message": f"Snapshot created: {request.snapshot_name}"
            }
        else:
            return {
                "success": False,
                "message": "Snapshots require database-backed configuration"
            }
    except Exception as e:
        raise server_error(e)


@router.post("/config/restore")
async def restore_snapshot(request: RestoreSnapshotRequest, http_request: Request, admin_user: str = Depends(require_admin)):
    """
    Restore configuration from a snapshot

    Example:
    ```json
    {
        "snapshot_name": "before_production_deploy"
    }
    ```
    """
    try:
        user = http_request.headers.get('X-User', 'api')

        success = config_manager.restore_snapshot(
            snapshot_name=request.snapshot_name,
            user=user
        )

        if success:
            return {
                "success": True,
                "message": f"Configuration restored from snapshot: {request.snapshot_name}",
                "config": config_manager.get_safe_config()
            }
        else:
            return {
                "success": False,
                "message": "Snapshots require database-backed configuration"
            }
    except Exception as e:
        raise server_error(e)


# ============================================
# PROVIDER TESTING
# ============================================

@router.post("/test")
async def test_connection(request: TestConnectionRequest, admin_user: str = Depends(require_admin)):
    """
    Test a provider configuration before applying

    Example:
    ```json
    {
        "provider_type": "llm",
        "provider": "anthropic",
        "config": {
            "api_key": "sk-ant-...",
            "model": "claude-sonnet-4-20250514"
        }
    }
    ```
    """
    try:
        result = config_manager.test_connection(
            provider_type=request.provider_type,
            provider=request.provider,
            config=request.config
        )

        return result
    except Exception as e:
        raise server_error(e)


# ============================================
# PROVIDER RELOAD
# ============================================

@router.post("/reload")
async def reload_providers(admin_user: str = Depends(require_admin)):
    """
    Reload LLM and Database providers with current config

    ⚠️ This will reinitialize providers - existing connections will be recreated

    This is the "hot reload" feature that allows runtime config changes
    without restarting the application.
    """
    try:
        # Import here to avoid circular dependency
        from src.api.app import reload_providers as app_reload_providers

        # Reload providers
        app_reload_providers()

        return {
            "success": True,
            "message": "Providers reloaded successfully",
            "timestamp": str(__import__('datetime').datetime.now())
        }
    except Exception as e:
        # If the reload function doesn't exist yet, provide helpful message
        return {
            "success": False,
            "message": "Provider reload not yet implemented in app.py",
            "note": "Configuration changes will take effect on next application restart"
        }


# ============================================
# SYSTEM INFO
# ============================================

@router.get("/info")
async def get_system_info(admin_user: str = Depends(require_admin)):
    """Get system and configuration info"""
    config = config_manager.get_config()

    return {
        "app": {
            "name": config.get('app', {}).get('name', 'SQLatte'),
            "version": config.get('app', {}).get('version', 'unknown'),
        },
        "llm": {
            "provider": config.get('llm', {}).get('provider'),
            "model": config.get('llm', {}).get(
                config.get('llm', {}).get('provider', 'anthropic'),
                {}
            ).get('model')
        },
        "database": {
            "provider": config.get('database', {}).get('provider'),
        },
        "config": {
            "runtime_overrides_active": len(config_manager.runtime_overrides) > 0,
            "db_enabled": config_manager.db_enabled,
            "config_file": config_manager.config_path
        },
        "features": {
            "hot_reload": True,
            "config_history": config_manager.db_enabled,
            "snapshots": config_manager.db_enabled
        }
    }


# ============================================
# PROMPTS MANAGEMENT ROUTES (Phase 2)
# ============================================

@router.get("/prompts")
async def get_prompts(admin_user: str = Depends(require_admin)):
    """
    Get all prompts (read from config)
    """
    try:
        config = config_manager.get_config()
        prompts = config.get('prompts', {})

        return {
            "success": True,
            "prompts": {
                "intent_detection": prompts.get('intent_detection', ''),
                "barista_personality": prompts.get('barista_personality', ''),
                "sql_generation": prompts.get('sql_generation', ''),
                "insights_generation": prompts.get('insights_generation', ''),
                "ops_insights_generation": prompts.get('ops_insights_generation', '')
            },
            "editable": True
        }

    except Exception as e:
        print(f"Error getting prompts: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/prompts/update")
async def update_prompt(request: Request, admin_user: str = Depends(require_admin)):
    """
    Update a specific prompt

    Body:
    {
        "prompt_type": "intent_detection",  // or barista_personality, sql_generation, insights_generation
        "prompt_value": "new prompt text...",
        "persist": true  // save to DB
    }
    """
    try:
        body = await request.json()
        prompt_type = body.get('prompt_type')
        prompt_value = body.get('prompt_value', '')
        persist = body.get('persist', True)

        if not prompt_type:
            return {
                "success": False,
                "error": "prompt_type is required"
            }

        # Validate prompt_type
        valid_types = ['intent_detection', 'barista_personality', 'sql_generation', 'insights_generation', 'ops_insights_generation']
        if prompt_type not in valid_types:
            return {
                "success": False,
                "error": f"Invalid prompt_type. Must be one of: {valid_types}"
            }

        # Update config
        updates = {
            'prompts': {
                prompt_type: prompt_value
            }
        }

        config_manager.update_config(
            updates=updates,
            persist=persist,
            user='admin',
            reason=f'Updated {prompt_type} prompt via admin panel'
        )

        return {
            "success": True,
            "message": f"Prompt '{prompt_type}' updated successfully",
            "persisted": persist
        }

    except Exception as e:
        print(f"Error updating prompt: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/prompts/reset")
async def reset_prompt(request: Request, admin_user: str = Depends(require_admin)):
    """
    Reset a prompt to default value from config.yaml

    Body:
    {
        "prompt_type": "intent_detection"
    }
    """
    try:
        body = await request.json()
        prompt_type = body.get('prompt_type')

        if not prompt_type:
            return {
                "success": False,
                "error": "prompt_type is required"
            }

        # Read default from config.yaml
        import yaml
        import os

        PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        CONFIG_PATH = os.path.join(PROJECT_ROOT, 'config', 'config.yaml')

        with open(CONFIG_PATH, 'r') as f:
            yaml_config = yaml.safe_load(f)

        default_prompts = yaml_config.get('prompts', {})
        default_value = default_prompts.get(prompt_type, '')

        if not default_value:
            return {
                "success": False,
                "error": f"No default prompt found for '{prompt_type}' in config.yaml"
            }

        # Update with default
        updates = {
            'prompts': {
                prompt_type: default_value
            }
        }

        config_manager.update_config(
            updates=updates,
            persist=True,
            user='admin',
            reason=f'Reset {prompt_type} prompt to default'
        )

        return {
            "success": True,
            "message": f"Prompt '{prompt_type}' reset to default",
            "default_value": default_value
        }

    except Exception as e:
        logger.error(f"Error resetting prompt: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ── Admin Token Management ────────────────────────────────────────────────────

@router.get("/tokens")
async def admin_list_tokens(admin_user: str = Depends(require_admin)):
    """List all API tokens across all users."""
    try:
        from src.core.config_db import get_config_db
        tokens = get_config_db().list_all_api_tokens()
        return {"tokens": tokens}
    except Exception as e:
        raise server_error(e)


@router.post("/token/revoke")
async def admin_revoke_token(
    request: Request,
    admin_user: str = Depends(require_admin),
):
    """Revoke any user's API token by its DB id (admin only)."""
    body = await request.json()
    token_id = body.get("id")
    if not token_id:
        raise HTTPException(400, "id is required")
    try:
        from src.core.config_db import get_config_db
        ok = get_config_db().admin_revoke_token(int(token_id))
        if not ok:
            raise HTTPException(404, "Token not found")
        return {"success": True, "message": "Token revoked"}
    except HTTPException:
        raise
    except Exception as e:
        raise server_error(e)


@router.delete("/token/{token_id}")
async def admin_delete_token(token_id: int, admin_user: str = Depends(require_admin)):
    """Permanently delete a revoked API token by its DB id (admin only)."""
    try:
        from src.core.config_db import get_config_db
        ok = get_config_db().admin_delete_token(token_id)
        if not ok:
            raise HTTPException(404, "Token not found or not revoked")
        return {"success": True, "message": "Token deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise server_error(e)


@router.get("/token-policy")
async def get_token_policy(admin_user: str = Depends(require_admin)):
    """Return the platform-wide token query budget policy."""
    from src.core.config_db import get_config_db
    limit = get_config_db().get_default_token_limit()
    return {"default_daily_limit": limit}


@router.post("/token-policy")
async def set_token_policy(
    request: Request,
    admin_user: str = Depends(require_admin),
):
    """Set the platform-wide default daily query limit for new tokens."""
    body = await request.json()
    raw = body.get("default_daily_limit")
    try:
        limit = int(raw) if raw not in (None, "", "null") else None
        if limit is not None and limit < 1:
            raise HTTPException(400, "limit must be a positive integer or null (unlimited)")
        from src.core.config_db import get_config_db
        get_config_db().set_default_token_limit(limit, changed_by=admin_user)
        return {
            "success": True,
            "default_daily_limit": limit,
            "message": f"Default daily limit set to {limit if limit is not None else 'unlimited'}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise server_error(e)


# ── MCP Mask Rules ────────────────────────────────────────────────────────────

@router.get("/mcp-mask-rules")
async def list_mask_rules(admin_user: str = Depends(require_admin)):
    from src.core.config_db import get_config_db
    rules = get_config_db().list_mask_rules()
    for r in rules:
        for k in ("created_at", "updated_at"):
            if r.get(k):
                r[k] = r[k].isoformat() if hasattr(r[k], "isoformat") else str(r[k])
    return {"rules": rules}


class MaskRuleCreateRequest(BaseModel):
    field_pattern: str
    strategy: str = "hash"
    description: Optional[str] = ""


@router.post("/mcp-mask-rules")
async def create_mask_rule(request: MaskRuleCreateRequest, admin_user: str = Depends(require_admin)):
    from src.core.config_db import get_config_db
    try:
        rule = get_config_db().create_mask_rule(
            field_pattern=request.field_pattern,
            strategy=request.strategy,
            description=request.description or "",
            created_by=admin_user,
        )
        return {"success": True, "rule": rule}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise server_error(e)


class MaskRuleUpdateRequest(BaseModel):
    field_pattern: Optional[str] = None
    strategy: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None


@router.put("/mcp-mask-rules/{rule_id}")
async def update_mask_rule(rule_id: int, request: MaskRuleUpdateRequest, admin_user: str = Depends(require_admin)):
    from src.core.config_db import get_config_db
    try:
        ok = get_config_db().update_mask_rule(
            rule_id=rule_id,
            field_pattern=request.field_pattern,
            strategy=request.strategy,
            enabled=request.enabled,
            description=request.description,
        )
        if not ok:
            raise HTTPException(404, "Rule not found")
        return {"success": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise server_error(e)


@router.delete("/mcp-mask-rules/{rule_id}")
async def delete_mask_rule(rule_id: int, admin_user: str = Depends(require_admin)):
    from src.core.config_db import get_config_db
    ok = get_config_db().delete_mask_rule(rule_id)
    if not ok:
        raise HTTPException(404, "Rule not found")
    return {"success": True}


@router.post("/token/set-limit")
async def admin_set_token_limit(
    request: Request,
    admin_user: str = Depends(require_admin),
):
    """Override the daily query limit on a specific token by DB id (admin only)."""
    body = await request.json()
    token_id = body.get("id")
    if not token_id:
        raise HTTPException(400, "id is required")
    raw = body.get("daily_query_limit")
    try:
        limit = int(raw) if raw not in (None, "", "null") else None
        if limit is not None and limit < 1:
            raise HTTPException(400, "limit must be a positive integer or null (unlimited)")
        from src.core.config_db import get_config_db
        ok = get_config_db().admin_set_token_limit(int(token_id), limit)
        if not ok:
            raise HTTPException(404, "Token not found")
        return {
            "success": True,
            "daily_query_limit": limit,
            "message": f"Token limit set to {limit if limit is not None else 'unlimited'}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise server_error(e)