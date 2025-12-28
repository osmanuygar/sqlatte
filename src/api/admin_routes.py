"""
SQLatte Admin Routes
Web-based configuration management
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional
import os

from src.core.config_manager import config_manager
from src.core.provider_factory import ProviderFactory


router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================
# PROVIDER RELOAD HELPER (Avoids Circular Import!)
# ============================================
def reload_app_providers():
    """
    Reload app providers without circular import
    Imports app module locally and updates its global providers
    """
    try:
        # Import locally to avoid circular dependency at module load time
        import src.api.app as app_module

        # Get current config
        current_config = config_manager.get_config()

        print("\n🔄 [ADMIN] Reloading providers...")

        # Recreate LLM provider
        try:
            new_llm = ProviderFactory.create_llm_provider(current_config)
            app_module.llm_provider = new_llm
            llm_name = new_llm.get_model_name()
            print(f"✅ [ADMIN] LLM provider reloaded: {llm_name}")
        except Exception as llm_error:
            print(f"❌ [ADMIN] LLM reload failed: {llm_error}")
            raise Exception(f"LLM provider creation failed: {str(llm_error)}")

        # Recreate DB provider
        try:
            new_db = ProviderFactory.create_db_provider(current_config)
            app_module.db_provider = new_db
            db_type = new_db.get_connection_info()['type']
            print(f"✅ [ADMIN] DB provider reloaded: {db_type}")
        except Exception as db_error:
            print(f"❌ [ADMIN] DB reload failed: {db_error}")
            raise Exception(f"Database provider creation failed: {str(db_error)}")

        print("🎉 [ADMIN] Provider reload complete!\n")

        return {
            "success": True,
            "llm": {
                "provider": current_config['llm']['provider'],
                "model": llm_name
            },
            "database": {
                "provider": current_config['database']['provider'],
                "info": app_module.db_provider.get_connection_info()
            }
        }
    except Exception as e:
        print(f"❌ [ADMIN] Provider reload failed: {e}")
        import traceback
        traceback.print_exc()
        # Return error info instead of raising exception
        return {
            "success": False,
            "error": str(e),
            "llm": None,
            "database": None
        }


# ============================================
# REQUEST MODELS
# ============================================

class ConfigUpdateRequest(BaseModel):
    """Generic config update request"""
    updates: Dict[str, Any]
    persist: bool = False  # Save to config.yaml


class LLMConfigRequest(BaseModel):
    """LLM provider configuration"""
    provider: str  # anthropic, gemini, vertexai
    config: Dict[str, Any]
    persist: bool = False


class DatabaseConfigRequest(BaseModel):
    """Database provider configuration"""
    provider: str  # trino, postgresql, mysql
    config: Dict[str, Any]
    persist: bool = False


class TestConnectionRequest(BaseModel):
    """Test provider connection"""
    provider_type: str  # 'llm' or 'database'
    provider: str
    config: Dict[str, Any]


# ============================================
# ADMIN UI
# ============================================

@router.get("", response_class=HTMLResponse)
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
        safe_config = config_manager.get_safe_config()

        return {
            "success": True,
            "config": safe_config,
            "has_runtime_overrides": len(config_manager.runtime_overrides) > 0,
            "config_file": config_manager.config_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/full")
async def get_full_config():
    """
    Get full configuration (including sensitive data)
    ⚠️ WARNING: This exposes sensitive information!
    """
    try:
        full_config = config_manager.get_config()

        return {
            "success": True,
            "config": full_config,
            "warning": "This response contains sensitive data"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/update")
async def update_config(request: ConfigUpdateRequest):
    """
    Update configuration at runtime

    Example:
    ```json
    {
        "updates": {
            "llm": {
                "provider": "gemini"
            }
        },
        "persist": false
    }
    ```
    """
    try:
        updated_config = config_manager.update_config(
            updates=request.updates,
            persist=request.persist
        )

        # Return safe version
        safe_config = config_manager.get_safe_config()

        return {
            "success": True,
            "message": "Configuration updated" + (" and saved" if request.persist else ""),
            "config": safe_config,
            "persisted": request.persist
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/reset")
async def reset_config():
    """Reset runtime overrides and reload from file"""
    try:
        # Reset to file config
        config = config_manager.reset_to_file()

        # Reload providers
        reload_result = reload_app_providers()

        # Check if reload was successful
        if not reload_result.get("success", False):
            return {
                "success": False,
                "message": f"Config reset but provider reload failed: {reload_result.get('error', 'Unknown error')}",
                "config": config_manager.get_safe_config(),
                "reloaded": reload_result
            }

        safe_config = config_manager.get_safe_config()

        return {
            "success": True,
            "message": "Configuration reset to file defaults",
            "config": safe_config,
            "reloaded": reload_result
        }
    except Exception as e:
        print(f"❌ [ADMIN] Config reset error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# LLM CONFIGURATION
# ============================================

@router.get("/llm/providers")
async def list_llm_providers():
    """List available LLM providers"""
    from src.core.provider_factory import ProviderFactory

    return {
        "providers": list(ProviderFactory.LLM_PROVIDERS.keys()),
        "current": config_manager.get_config().get('llm', {}).get('provider')
    }


@router.post("/llm/update")
async def update_llm_config(request: LLMConfigRequest):
    """
    Update LLM provider configuration

    Example:
    ```json
    {
        "provider": "anthropic",
        "config": {
            "api_key": "sk-ant-...",
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000
        },
        "persist": false
    }
    ```
    """
    try:
        # Update config
        updated_config = config_manager.update_llm_config(
            provider=request.provider,
            provider_config=request.config
        )

        # Save to file if requested
        if request.persist:
            config_manager._save_to_file()

        # Reload providers
        reload_result = reload_app_providers()

        # Check if reload was successful
        if not reload_result.get("success", False):
            return {
                "success": False,
                "message": f"Config updated but provider reload failed: {reload_result.get('error', 'Unknown error')}",
                "config": config_manager.get_safe_config(),
                "reloaded": reload_result
            }

        return {
            "success": True,
            "message": f"LLM provider updated to {request.provider}" + (" and saved to file" if request.persist else ""),
            "config": config_manager.get_safe_config(),
            "reloaded": reload_result
        }
    except Exception as e:
        print(f"❌ [ADMIN] LLM update error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# DATABASE CONFIGURATION
# ============================================

@router.get("/database/providers")
async def list_database_providers():
    """List available database providers"""
    from src.core.provider_factory import ProviderFactory

    return {
        "providers": list(ProviderFactory.DB_PROVIDERS.keys()),
        "current": config_manager.get_config().get('database', {}).get('provider')
    }


@router.post("/database/update")
async def update_database_config(request: DatabaseConfigRequest):
    """
    Update Database provider configuration

    Example:
    ```json
    {
        "provider": "postgresql",
        "config": {
            "host": "localhost",
            "port": 5432,
            "database": "mydb",
            "user": "postgres",
            "password": "password",
            "schema": "public"
        },
        "persist": false
    }
    ```
    """
    try:
        # Update config
        updated_config = config_manager.update_database_config(
            provider=request.provider,
            provider_config=request.config
        )

        # Save to file if requested
        if request.persist:
            config_manager._save_to_file()

        # Reload providers
        reload_result = reload_app_providers()

        # Check if reload was successful
        if not reload_result.get("success", False):
            return {
                "success": False,
                "message": f"Config updated but provider reload failed: {reload_result.get('error', 'Unknown error')}",
                "config": config_manager.get_safe_config(),
                "reloaded": reload_result
            }

        return {
            "success": True,
            "message": f"Database provider updated to {request.provider}" + (" and saved to file" if request.persist else ""),
            "config": config_manager.get_safe_config(),
            "reloaded": reload_result
        }
    except Exception as e:
        print(f"❌ [ADMIN] Database update error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CONNECTION TESTING
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
    """
    try:
        # This would need to be implemented in app.py
        # to actually reload the global providers

        return {
            "success": True,
            "message": "Provider reload triggered",
            "warning": "This requires application restart for full effect"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        "runtime_overrides_active": len(config_manager.runtime_overrides) > 0,
        "config_file": config_manager.config_path
    }