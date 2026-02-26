"""
SQLatte Admin API Routes - Enhanced with DB Config Management
Provides comprehensive configuration management with:
- Runtime configuration updates
- Configuration history & audit trail
- Configuration snapshots & rollback
- Test before apply
- Hot reload without restart
"""

import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from src.core.config_manager_enhanced import config_manager

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


# ============================================
# ADMIN PAGE
# ============================================

@router.get("/", response_class=HTMLResponse)
async def admin_page():
    """Serve admin configuration page"""
    admin_html_path = os.path.join(
        os.path.dirname(__file__),
        '../../frontend/admin.html'
    )

    if not os.path.exists(admin_html_path):
        return HTMLResponse(
            content="""
            <html>
                <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                    <h1>⚠️ Admin Page Not Found</h1>
                    <p>Create frontend/admin.html to enable the admin interface</p>
                </body>
            </html>
            """,
            status_code=404
        )

    with open(admin_html_path, 'r') as f:
        return HTMLResponse(content=f.read())


# ============================================
# CONFIG MANAGEMENT
# ============================================

@router.get("/config")
async def get_current_config():
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
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/config")
async def update_config(request: ConfigUpdateRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/llm")
async def update_llm_config(request: LLMConfigRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/database")
async def update_database_config(request: DatabaseConfigRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/email")
async def update_email_config(request: EmailConfigRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


class SchedulerConfigRequest(BaseModel):
    """Request model for Scheduler config updates"""
    config: Dict[str, Any]
    persist: bool = False


@router.put("/config/scheduler")
async def update_scheduler_config(request: SchedulerConfigRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


class InsightsConfigRequest(BaseModel):
    """Request model for Insights config updates"""
    config: Dict[str, Any]
    persist: bool = False


@router.put("/config/insights")
async def update_insights_config(request: InsightsConfigRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


class ExportConfigRequest(BaseModel):
    """Request model for Export config updates"""
    config: Dict[str, Any]
    persist: bool = False


@router.put("/config/export")
async def update_export_config(request: ExportConfigRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/email")
async def test_email_connection(request: Dict[str, Any]):
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
async def update_email_config(request: EmailConfigRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/reset")
async def reset_config():
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
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CONFIG HISTORY & SNAPSHOTS
# ============================================

@router.get("/config/history")
async def get_config_history(key: Optional[str] = None, limit: int = 100):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/snapshot")
async def create_snapshot(request: SnapshotRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/restore")
async def restore_snapshot(request: RestoreSnapshotRequest, http_request: Request):
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
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# PROVIDER TESTING
# ============================================

@router.post("/test")
async def test_connection(request: TestConnectionRequest):
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
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# PROVIDER RELOAD
# ============================================

@router.post("/reload")
async def reload_providers():
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
async def get_system_info():
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
async def get_prompts():
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
                "insights_generation": prompts.get('insights_generation', '')
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
async def update_prompt(request: Request):
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
        valid_types = ['intent_detection', 'barista_personality', 'sql_generation', 'insights_generation']
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
async def reset_prompt(request: Request):
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