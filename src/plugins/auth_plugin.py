"""
SQLatte Authentication Plugin - Enhanced Version (Backward Compatible)
With all standard widget features + config-based restrictions
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Dict, Any, List
import asyncio
import re
import threading
import time as _time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from src.plugins.base_plugin import BasePlugin
from src.plugins.session_manager import auth_session_manager
from src.core.conversation_manager import conversation_manager
import time
from src.core.provider_factory import ProviderFactory
from src.core.error_utils import server_error

# ── M-02: Input Validation ────────────────────────────────────────────────────

_SAFE_HOST = re.compile(
    r'^(?:'
    r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9]{1,63}'  # hostname
    r'|'
    r'(?:\d{1,3}\.){3}\d{1,3}'          # IPv4
    r')$'
)
_ALLOWED_DB_TYPES = {"trino", "postgresql", "mysql", "bigquery"}
_ALLOWED_SCHEMES  = {"http", "https"}


class LoginRequest(BaseModel):
    """Login request model — with input validation."""
    username: str
    password: str
    database_type: str
    host: str
    port: int
    catalog: Optional[str] = None
    schema: Optional[str] = 'default'
    database: Optional[str] = None
    http_scheme: Optional[str] = 'https'

    @field_validator("database_type")
    @classmethod
    def validate_db_type(cls, v: str) -> str:
        if v not in _ALLOWED_DB_TYPES:
            raise ValueError(f"database_type must be one of {sorted(_ALLOWED_DB_TYPES)}")
        return v

    @field_validator("http_scheme")
    @classmethod
    def validate_scheme(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _ALLOWED_SCHEMES:
            raise ValueError("http_scheme must be 'http' or 'https'")
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("port must be between 1 and 65535")
        return v

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        if not v or len(v) > 253 or not _SAFE_HOST.match(v):
            raise ValueError("host contains invalid characters or format")
        return v

    @field_validator("username", "password")
    @classmethod
    def validate_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field must not be empty")
        return v


# ── M-03: Login Brute-Force Protection ───────────────────────────────────────
# Tracks failed login attempts per IP. After MAX_ATTEMPTS failures within
# WINDOW_SECONDS the IP is locked for LOCKOUT_SECONDS.

_LOGIN_MAX_ATTEMPTS  = 10       # failures before lockout
_LOGIN_WINDOW_SEC    = 300      # rolling window (5 min)
_LOGIN_LOCKOUT_SEC   = 600      # lockout duration (10 min)

_login_attempts: Dict[str, list] = defaultdict(list)   # ip → [timestamp, ...]
_login_lockouts: Dict[str, float] = {}                  # ip → unlock_at
_login_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host or "unknown")


def _check_login_allowed(ip: str) -> None:
    """Raise HTTP 429 if the IP is locked out, otherwise update attempt window."""
    now = _time.time()
    with _login_lock:
        unlock_at = _login_lockouts.get(ip, 0)
        if unlock_at > now:
            remaining = int(unlock_at - now)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed login attempts. Try again in {remaining}s.",
                headers={"Retry-After": str(remaining)},
            )
        # Purge stale timestamps
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOGIN_WINDOW_SEC]


def _record_failed_login(ip: str) -> None:
    now = _time.time()
    with _login_lock:
        _login_attempts[ip].append(now)
        if len(_login_attempts[ip]) >= _LOGIN_MAX_ATTEMPTS:
            _login_lockouts[ip] = now + _LOGIN_LOCKOUT_SEC
            _login_attempts[ip].clear()


def _clear_login_attempts(ip: str) -> None:
    with _login_lock:
        _login_attempts.pop(ip, None)
        _login_lockouts.pop(ip, None)


class ValidateSessionRequest(BaseModel):
    """Session validation request"""
    session_id: str


class AuthPlugin(BasePlugin):
    """
    Enhanced Authentication Plugin for SQLatte

    New Features:
    - Config-based DB restrictions (optional)
    - All standard widget features support
    - Backward compatible with existing setup

    Backward Compatible:
    - Works with existing login form
    - Optional config-based restrictions
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.session_manager = auth_session_manager
        self.executor = ThreadPoolExecutor(
            max_workers=config.get('max_workers', 40)  # Increased from 10
        )

        # Optional config-based restrictions (backward compatible)
        self.allowed_db_types = config.get('allowed_db_types', [])
        raw_catalogs = config.get('allowed_catalogs', [])

        if raw_catalogs and isinstance(raw_catalogs[0], dict):
            # Yeni format: [{name: "...", allowed_schemas: [...]}]
            self.catalog_schema_map = {
                item['name']: item.get('allowed_schemas', [])
                for item in raw_catalogs
            }
            self.allowed_catalogs = list(self.catalog_schema_map.keys())
        else:
            # Eski format: ["catalog1", "catalog2"] - backward compatible
            self.catalog_schema_map = {}
            self.allowed_catalogs = raw_catalogs

        self.allowed_schemas = config.get('allowed_schemas', [])  # fallback
        self.db_provider = config.get('db_provider', None)  # Optional
        self.db_host = config.get('db_host', None)  # Optional
        self.db_port = config.get('db_port', None)  # Optional

        print(f"🔐 Auth Plugin Enhanced:")
        print(f"   - Thread Pool: {self.executor._max_workers} workers")
        if self.allowed_catalogs:
            print(f"   - Allowed Catalogs: {self.allowed_catalogs}")
        if self.allowed_schemas:
            print(f"   - Allowed Schemas: {self.allowed_schemas}")

    def initialize(self, app: FastAPI) -> None:
        """Initialize auth plugin"""
        print(f"🔐 Initializing Enhanced Auth Plugin...")
        self.session_manager.start_cleanup_task()
        self.app = app

    def register_routes(self, app: FastAPI) -> None:
        """Register authentication routes"""

        @app.get("/auth/config")
        async def get_auth_config():
            """
            NEW ENDPOINT: Return server config for client-side restrictions

            This is optional - if no restrictions configured, returns empty lists
            """
            return JSONResponse({
                "allowed_db_types": self.allowed_db_types,
                "allowed_catalogs": self.allowed_catalogs,
                "allowed_schemas": self.allowed_schemas,
                "catalog_schema_map": self.catalog_schema_map,
                "db_provider": self.db_provider,
                "db_host": self.db_host,
                "db_port": self.db_port
            })

        @app.post("/auth/login")
        async def login(request: LoginRequest, http_request: Request):
            """
            Login endpoint — validates credentials and creates a session.

            M-02: Input is validated by LoginRequest Pydantic validators.
            M-03: Brute-force protection — IP locked after repeated failures.
            """
            ip = _client_ip(http_request)

            # M-03: Reject locked-out IPs before touching the DB
            _check_login_allowed(ip)

            try:
                # Catalog/schema allowlist check
                if self.allowed_catalogs and request.catalog not in self.allowed_catalogs:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Catalog '{request.catalog}' not allowed"
                    )

                if self.allowed_schemas and request.schema not in self.allowed_schemas:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Schema '{request.schema}' not allowed"
                    )

                # Build database config from login request
                db_config = self._build_db_config(request)

                # Test connection in thread pool (non-blocking)
                loop = asyncio.get_event_loop()
                is_valid = await loop.run_in_executor(
                    self.executor,
                    self._test_db_connection,
                    request.database_type,
                    db_config
                )

                if not is_valid:
                    _record_failed_login(ip)   # M-03: count the failure
                    raise HTTPException(
                        status_code=401,
                        detail="Invalid credentials or connection failed"
                    )

                # Create session
                session_id = self.session_manager.create_session(
                    username=request.username,
                    db_config={
                        'provider': request.database_type,
                        request.database_type: db_config
                    }
                )

                # M-03: Successful login — reset the failure counter for this IP
                _clear_login_attempts(ip)

                return {
                    "success": True,
                    "session_id": session_id,
                    "message": "Login successful",
                    "user": {
                        "username": request.username,
                        "database_type": request.database_type,
                        "host": request.host
                    },
                    "user_info": {
                        "username": request.username,
                        "catalog": request.catalog,
                        "schema": request.schema
                    }
                }

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Login error: {e}")
                import traceback
                traceback.print_exc()
                raise server_error(e)

        @app.post("/auth/logout")
        async def logout(session_id: str = Header(..., alias="X-Session-ID")):
            """Logout - Destroy session"""
            success = self.session_manager.destroy_session(session_id)

            if not success:
                raise HTTPException(
                    status_code=404,
                    detail="Session not found"
                )

            return {
                "success": True,
                "message": "Logged out successfully"
            }

        @app.post("/auth/validate")
        async def validate_session(request: ValidateSessionRequest):
            """Validate if session is still active"""
            is_valid = self.session_manager.validate_session(request.session_id)

            return {
                "valid": is_valid,
                "session_id": request.session_id
            }

        @app.get("/auth/session-info")
        async def get_session_info(session_id: str = Header(..., alias="X-Session-ID")):
            """Get current session information"""
            session = self.session_manager.get_session(session_id)

            if not session:
                raise HTTPException(
                    status_code=401,
                    detail="Session expired or invalid"
                )

            return {
                "username": session.username,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat()
            }

        @app.get("/auth/stats")
        async def get_auth_stats():
            """Get authentication statistics"""
            return {
                "active_sessions": self.session_manager.get_active_session_count(),
                "total_sessions": len(self.session_manager.sessions)
            }

        @app.get("/auth/user-stats")
        async def get_user_stats(session_id: str = Header(..., alias="X-Session-ID")):
            """Get token usage stats for the currently logged-in user"""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(status_code=401, detail="Session expired or invalid")

            try:
                from src.core.audit_log_db import audit_log_db
                if audit_log_db is None:
                    return {"today": {}, "week": {}, "by_operation": [], "available": False}
                stats = audit_log_db.get_user_stats(session.username)
                stats["available"] = True
                stats["username"] = session.username
                return stats
            except Exception as e:
                print(f"❌ user-stats error: {e}")
                return {"today": {}, "week": {}, "by_operation": [], "available": False}

        @app.get("/auth/tables")
        async def get_tables(session_id: str = Header(..., alias="X-Session-ID")):
            """Get available tables for authenticated user"""
            try:
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

                loop = asyncio.get_event_loop()
                tables = await loop.run_in_executor(
                    self.executor,
                    self._get_tables_for_session,
                    session.db_config
                )

                return {"tables": tables}

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Error loading tables: {e}")
                import traceback
                traceback.print_exc()
                raise server_error(e)

        @app.get("/auth/schema/{table_name}")
        async def get_schema(
            table_name: str,
            session_id: str = Header(..., alias="X-Session-ID")
        ):
            """Get schema for a specific table"""
            from src.core.sql_validator import validate_identifier
            try:
                validate_identifier(table_name)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid table name")

            try:
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

                loop = asyncio.get_event_loop()
                schema = await loop.run_in_executor(
                    self.executor,
                    self._get_schema_for_session,
                    session.db_config,
                    table_name
                )

                return {
                    "table": table_name,
                    "schema": schema
                }

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Error loading schema: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to load schema"
                )

        @app.post("/auth/schema/multiple")
        async def get_multiple_schemas(
            request: Dict[str, List[str]],
            session_id: str = Header(..., alias="X-Session-ID")
        ):
            """
            NEW ENDPOINT: Get combined schema for multiple tables
            """
            try:
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

                tables = request.get('tables', [])
                if not tables:
                    raise HTTPException(
                        status_code=400,
                        detail="No tables provided"
                    )

                loop = asyncio.get_event_loop()
                schemas = []

                for table in tables:
                    schema = await loop.run_in_executor(
                        self.executor,
                        self._get_schema_for_session,
                        session.db_config,
                        table
                    )
                    schemas.append(f"Table: {table}\n{schema}")

                combined = "\n\n".join(schemas)

                return {
                    "combined_schema": combined
                }

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Error loading schemas: {e}")
                raise server_error(e)

        @app.post("/auth/query")
        async def execute_query(
                request: dict,
                session_id: str = Header(..., alias="X-Session-ID")
        ):
            """
            Execute SQL query with CONVERSATION MEMORY
            """
            start_time = time.time()
            session = None
            selected_tables = []
            try:
                from src.core.conversation_manager import conversation_manager
                from src.core.query_history import query_history

                # 1. Validate auth session
                session = self.session_manager.get_session(session_id)
                if not session:
                    raise HTTPException(401, "Session expired or invalid")

                question = request.get('question', '')
                table_schema = request.get('table_schema', '') or request.get('schema', '')
                bypass_intent = bool(request.get('bypass_intent', False))

                if not question:
                    raise HTTPException(400, "Question is required")

                # Extract tables from schema
                if table_schema:
                    for line in table_schema.split('\n'):
                        if line.startswith('Table:'):
                            table_name = line.replace('Table:', '').strip()
                            if '.' in table_name:
                                table_name = table_name.split('.')[-1]
                            selected_tables.append(table_name)

                # 2. Get or create conversation session
                if not session.conversation_id:
                    conv_id = conversation_manager.create_session()
                    session.conversation_id = conv_id
                    print(f"🆕 Conversation session created: {conv_id[:8]}... for user: {session.username}")
                else:
                    conv_id = session.conversation_id

                # 3. Add user message to conversation
                conversation_manager.add_message(
                    conv_id,
                    role="user",
                    content=question,
                    metadata={"username": session.username}
                )

                # 4. Execute query WITH conversation_id
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    self._execute_query_for_session,
                    session.db_config,
                    question,
                    table_schema,
                    conv_id,
                    session_id,
                    session.username,
                    bypass_intent,
                )
                execution_time = (time.time() - start_time) * 1000

                # 5. Add assistant response to conversation
                if "error" in result:
                    content = result["error"]
                    metadata = {"type": "error"}
                    query_history.add_query(
                        session_id=session_id,
                        question=question,
                        sql="",
                        tables=selected_tables,
                        row_count=0,
                        execution_time_ms=execution_time,
                        success=False,
                        error_message=result["error"],
                        widget_type="auth",
                        user_id=session.username
                    )
                elif "sql" in result:
                    content = f"Generated SQL with {len(result.get('data', []))} rows"
                    metadata = {
                        "type": "sql",
                        "sql": result["sql"],
                        "row_count": len(result.get("data", []))
                    }
                    query_history.add_query(
                        session_id=session_id,
                        question=question,
                        sql=result["sql"],
                        tables=selected_tables,
                        row_count=len(result.get("data", [])),
                        execution_time_ms=execution_time,
                        success=True,
                        widget_type="auth",
                        user_id=session.username
                    )
                elif "response_type" in result and result["response_type"] == "warning":
                    content = f"[Security Warning] {result.get('reason', '')}"
                    metadata = {"type": "warning"}
                elif "response_type" in result and result["response_type"] == "chat":
                    content = result["message"]
                    metadata = {"type": "chat"}
                else:
                    content = str(result)
                    metadata = {"type": "unknown"}

                conversation_manager.add_message(
                    conv_id,
                    role="assistant",
                    content=content,
                    metadata=metadata
                )

                # 6. Return result
                result["conversation_id"] = conv_id
                return result

            except HTTPException:
                raise
            except Exception as e:
                execution_time = (time.time() - start_time) * 1000

                # ← YENİ: Track unexpected errors
                from src.core.query_history import query_history
                query_history.add_query(
                    session_id=session_id,
                    question=request.get('question', ''),
                    sql="",
                    tables=[],
                    row_count=0,
                    execution_time_ms=execution_time,
                    success=False,
                    error_message=str(e),
                    widget_type="auth",
                    user_id=session.username if 'session' in locals() else None
                )

                print(f"❌ Auth query error: {e}")
                import traceback
                traceback.print_exc()
                raise server_error(e)

        @app.get("/auth/conversation/history")
        async def get_conversation_history(
                session_id: str = Header(..., alias="X-Session-ID"),
                limit: int = 50
        ):
            """Get conversation history for authenticated user"""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(401, "Session expired")

            if not session.conversation_id:
                return {"messages": [], "total": 0}

            history = conversation_manager.get_session_history(session.conversation_id)

            return {
                "messages": history[-limit:] if limit else history,
                "total": len(history),
                "conversation_id": session.conversation_id
            }

        # YENİ ENDPOINT: Clear conversation
        @app.post("/auth/conversation/clear")
        async def clear_conversation(
                session_id: str = Header(..., alias="X-Session-ID")
        ):
            """Clear conversation history"""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(401, "Session expired")

            if session.conversation_id:
                conversation_manager.clear_session(session.conversation_id)
                print(f"🗑️ Conversation cleared for: {session.username}")

            return {"message": "Conversation cleared", "success": True}

        # ── API Token endpoints ──────────────────────────────────────────────────

        @app.post("/auth/token/generate")
        async def generate_api_token(
            request: dict,
            session_id: str = Header(..., alias="X-Session-ID")
        ):
            """Generate a persisted API token from an active session."""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(401, "Session expired or invalid")

            try:
                from src.core.config_db import get_config_db
                config_db = get_config_db()

                ttl_hours = int(request.get("ttl_hours", 24))
                description = request.get("description", "MCP Token")

                raw_limit = request.get("daily_query_limit")
                daily_query_limit = int(raw_limit) if raw_limit not in (None, "", 0, "0") else None

                token = config_db.create_api_token(
                    username=session.username,
                    db_config=session.db_config,
                    ttl_hours=ttl_hours,
                    description=description,
                    daily_query_limit=daily_query_limit,
                )

                platform_default = config_db.get_default_token_limit()
                if daily_query_limit is None:
                    effective_limit = platform_default
                elif platform_default is not None:
                    effective_limit = min(daily_query_limit, platform_default)
                else:
                    effective_limit = daily_query_limit

                limit_str = f"{effective_limit} queries/day" if effective_limit is not None else "unlimited"
                return {
                    "success": True,
                    "token": token,
                    "ttl_hours": ttl_hours,
                    "description": description,
                    "daily_query_limit": effective_limit,
                    "message": f"Token valid for {ttl_hours} hours, {limit_str}. Set SQLATTE_TOKEN in your MCP config.",
                }
            except Exception as e:
                print(f"❌ Token generate error: {e}")
                raise server_error(e)

        @app.post("/auth/token/validate")
        async def validate_api_token(request: dict):
            """Validate an API token and return a fresh session_id."""
            token = request.get("token", "")
            if not token:
                raise HTTPException(400, "token is required")

            try:
                from src.core.config_db import get_config_db
                config_db = get_config_db()
                result = config_db.validate_api_token(token)
                if not result:
                    raise HTTPException(401, "Invalid, expired, or revoked token")
                if result.get("_error") == "budget_exceeded":
                    raise HTTPException(
                        429,
                        f"Daily query budget of {result['daily_limit']} queries exceeded. "
                        f"Resets at midnight UTC."
                    )

                new_session_id = self.session_manager.create_session(
                    username=result["username"],
                    db_config=result["db_config"]
                )
                return {"success": True, "session_id": new_session_id, "username": result["username"]}
            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Token validate error: {e}")
                raise server_error(e)

        @app.post("/auth/token/revoke")
        async def revoke_api_token(
            request: dict,
            session_id: str = Header(..., alias="X-Session-ID")
        ):
            """Revoke an API token (owner only)."""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(401, "Session expired or invalid")

            token = request.get("token", "")
            if not token:
                raise HTTPException(400, "token is required")

            try:
                from src.core.config_db import get_config_db
                config_db = get_config_db()
                ok = config_db.revoke_api_token(token=token, username=session.username)
                if not ok:
                    raise HTTPException(404, "Token not found or not owned by you")
                return {"success": True, "message": "Token revoked"}
            except HTTPException:
                raise
            except Exception as e:
                raise server_error(e)

        @app.get("/auth/tokens")
        async def list_api_tokens(
            session_id: str = Header(..., alias="X-Session-ID")
        ):
            """List active API tokens for the current user."""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(401, "Session expired or invalid")

            try:
                from src.core.config_db import get_config_db
                config_db = get_config_db()
                tokens = config_db.list_api_tokens(session.username)
                return {"tokens": tokens, "username": session.username}
            except Exception as e:
                raise server_error(e)

        # ── Auto-session endpoint ──────────────────────────────────────────────
        # Creates a server-credential-backed short-lived session for embedded
        # widgets (e.g. sqlatte-badge.js) that have no user credentials.
        # Disabled unless plugins.auth.auto_session.enabled = true in config.

        _auto_cfg = self.config.get("auto_session", {})
        _auto_enabled = _auto_cfg.get("enabled", False)

        @app.post("/auth/auto-session")
        async def create_auto_session(http_request: Request):
            """
            Create a server-credential-backed auto session for embedded widgets.
            The server reads its configured database credentials (e.g. BigQuery
            service account) and returns a short-lived session_id.

            Requires plugins.auth.auto_session.enabled = true in config.yaml.
            """
            if not _auto_enabled:
                raise HTTPException(403, "Auto-session is not enabled")

            # Optional Origin check
            allowed_origins = _auto_cfg.get("allowed_origins", [])
            if allowed_origins:
                origin = http_request.headers.get("origin", "")
                if origin not in allowed_origins:
                    raise HTTPException(403, f"Origin '{origin}' not allowed for auto-session")

            try:
                from src.core.config_manager_enhanced import config_manager
                full_config = config_manager.get_config()

                # Build session db_config from the server's database section
                db_section = full_config.get("database", {})
                provider = db_section.get("provider", "")
                if not provider:
                    raise HTTPException(500, "No database provider configured on server")

                provider_cfg = db_section.get(provider, {})
                if not provider_cfg:
                    raise HTTPException(500, f"No config found for provider '{provider}'")

                db_config = {
                    "provider": provider,
                    provider: provider_cfg,
                }

                ttl_hours = _auto_cfg.get("ttl_hours", 1)
                ttl_minutes = int(ttl_hours * 60)
                label = _auto_cfg.get("label", "auto-session")

                session_id = self.session_manager.create_session(
                    username=label,
                    db_config=db_config,
                    ttl_minutes=ttl_minutes,
                )

                return {
                    "success": True,
                    "session_id": session_id,
                    "ttl_minutes": ttl_minutes,
                }

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Auto-session error: {e}")
                import traceback
                traceback.print_exc()
                raise HTTPException(500, f"Auto-session creation failed: {str(e)}")

    def _build_db_config(self, request: LoginRequest) -> Dict[str, Any]:
        """Build database config from login request"""
        config = {
            'host': request.host,
            'port': request.port,
            'user': request.username,
            'password': request.password,
        }

        # Database-specific fields
        if request.database_type == 'trino':
            if request.catalog:
                config['catalog'] = request.catalog
            if request.schema:
                config['schema'] = request.schema
            config['http_scheme'] = request.http_scheme

        elif request.database_type == 'postgresql':
            if request.database:
                config['database'] = request.database
            else:
                config['database'] = 'postgres'

        elif request.database_type == 'mysql':
            if request.database:
                config['database'] = request.database
            else:
                config['database'] = 'mysql'

        return config

    def _test_db_connection(
        self,
        db_type: str,
        db_config: Dict[str, Any]
    ) -> bool:
        """Test database connection"""
        try:
            wrapped_config = {
                'database': {
                    'provider': db_type,
                    db_type: db_config
                }
            }

            db_provider = ProviderFactory.create_db_provider(wrapped_config)
            tables = db_provider.get_tables()

            print(f"✅ Connection test successful: {len(tables)} tables found")
            return True

        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            return False

    def _get_tables_for_session(self, db_config: Dict[str, Any]) -> List[str]:
        """Get tables for a session's DB connection"""
        try:
            wrapped_config = {'database': db_config}
            db_provider = ProviderFactory.create_db_provider(wrapped_config)
            tables = db_provider.get_tables()

            print(f"📊 Retrieved {len(tables)} tables")
            return tables

        except Exception as e:
            print(f"❌ Failed to get tables: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _get_schema_for_session(
        self,
        db_config: Dict[str, Any],
        table_name: str
    ) -> str:
        """Get schema for a specific table"""
        try:
            wrapped_config = {'database': db_config}
            db_provider = ProviderFactory.create_db_provider(wrapped_config)
            schema = db_provider.get_table_schema(table_name)

            print(f"📋 Retrieved schema for table: {table_name}")
            return schema

        except Exception as e:
            print(f"❌ Failed to get schema for {table_name}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _execute_query_for_session(
            self,
            db_config: Dict[str, Any],
            question: str,
            table_schema: str,
            conversation_id: str = None,
            session_id: str = None,
            user_id: str = None,
            bypass_intent: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute query with CONVERSATION CONTEXT support and model routing.
        """
        try:
            from src.core.config_manager_enhanced import config_manager
            from src.core.conversation_manager import conversation_manager
            from src.core.audit_log_db import audit_log_db

            wrapped_db_config = {'database': db_config}
            db_provider = ProviderFactory.create_db_provider(wrapped_db_config)

            llm_config = config_manager.get_config()
            # Use task-specific model routing, same as the default widget
            llm_intent = ProviderFactory.create_llm_provider_for_task(llm_config, "intent_detection")
            llm_sql    = ProviderFactory.create_llm_provider_for_task(llm_config, "sql")
            llm_chat   = ProviderFactory.create_llm_provider_for_task(llm_config, "chat")

            print(f"🤖 [Auth] intent={llm_intent.get_model_name()} | sql={llm_sql.get_model_name()} | chat={llm_chat.get_model_name()}")
            print(f"🤖 Processing query: {question[:50]}...")

            schema_info = table_schema if table_schema else "No schema provided."

            if bypass_intent:
                print("⚡ [MCP] Bypassing intent detection — going directly to SQL")
                intent_result = {"intent": "sql", "confidence": 1.0}
            else:
                intent_result = llm_intent.determine_intent(question, schema_info)
                if audit_log_db and session_id:
                    _u = getattr(llm_intent, "last_token_usage", {})
                    audit_log_db.log(
                        session_id=session_id, operation_type="intent_detection",
                        model_name=llm_intent.get_model_name(), question=question,
                        prompt_preview=question[:500],
                        input_tokens=_u.get("input_tokens", 0),
                        output_tokens=_u.get("output_tokens", 0),
                        user_id=user_id, widget_type="auth",
                    )
                print(f"🎯 Intent: {intent_result['intent']} (confidence: {intent_result['confidence']})")

            if intent_result["intent"] == "sql" and intent_result["confidence"] > 0.6:
                if schema_info == "No schema provided.":
                    return {
                        "error": "☕ Please select one or more tables first to query your data."
                    }

                enhanced_question = question
                if conversation_id:
                    conv_context = conversation_manager.get_conversation_context(conversation_id)
                    if len(conv_context) > 1:
                        context_summary = "\n\nRecent conversation:\n"
                        for msg in conv_context[-5:]:
                            if msg['role'] == 'user':
                                context_summary += f"User: {msg['content']}\n"
                            elif msg['role'] == 'assistant':
                                context_summary += f"Assistant: {str(msg['content'])[:100]}...\n"
                        enhanced_question = f"{question}\n\nContext from previous messages: {context_summary}"
                        print(f"💬 Using conversation context ({len(conv_context)} messages)")

                # Generate SQL with task-routed model
                sql_query, explanation = llm_sql.generate_sql(enhanced_question, schema_info)
                print(f"📝 Generated SQL: {sql_query[:100]}...")

                if not sql_query:
                    return {
                        "error": "Failed to generate SQL query. Please try rephrasing your question."
                    }

                from src.core.sql_validator import is_select_only, violation_reason, risk_score
                _sql_valid = is_select_only(sql_query)
                _risk = risk_score(sql_query)
                _u = getattr(llm_sql, "last_token_usage", {})
                _full_tables = [
                    line.replace("Table:", "").strip()
                    for line in schema_info.split("\n")
                    if line.startswith("Table:")
                ]
                _prov = db_config.get("provider", "")
                _catalog = (
                    db_config.get(_prov, {}).get("catalog")
                    or db_config.get(_prov, {}).get("project_id")
                    or db_config.get(_prov, {}).get("database")
                )
                _widget = "mcp" if bypass_intent else "auth"

                if not _sql_valid:
                    reason = violation_reason(sql_query)
                    print(f"🚫 Blocked non-SELECT query (auth): {reason} | SQL: {sql_query[:120]}")
                    if audit_log_db and session_id:
                        audit_log_db.log(
                            session_id=session_id, operation_type="sql_generation",
                            model_name=llm_sql.get_model_name(), question=question,
                            prompt_preview=enhanced_question[:500],
                            input_tokens=_u.get("input_tokens", 0),
                            output_tokens=_u.get("output_tokens", 0),
                            user_id=user_id, widget_type=_widget,
                            catalog_name=_catalog,
                            table_names=_full_tables or None,
                            generated_sql=sql_query,
                            risk_score=_risk,
                            sql_valid=False,
                        )
                    return {
                        "response_type": "warning",
                        "sql": sql_query,
                        "reason": reason,
                        "message": f"Only SELECT queries are permitted. {reason}.",
                    }

                import time as _time
                _exec_start = _time.time()
                columns, data = db_provider.execute_query(sql_query)
                _execution_ms = int((_time.time() - _exec_start) * 1000)
                print(f"✅ Query executed: {len(data)} rows returned")

                if audit_log_db and session_id:
                    audit_log_db.log(
                        session_id=session_id, operation_type="sql_generation",
                        model_name=llm_sql.get_model_name(), question=question,
                        prompt_preview=enhanced_question[:500],
                        input_tokens=_u.get("input_tokens", 0),
                        output_tokens=_u.get("output_tokens", 0),
                        user_id=user_id, widget_type=_widget,
                        catalog_name=_catalog,
                        table_names=_full_tables or None,
                        generated_sql=sql_query,
                        risk_score=_risk,
                        sql_valid=True,
                        execution_ms=_execution_ms,
                    )

                row_cap = None
                if bypass_intent:
                    mcp_cfg = llm_config.get("mcp", {})
                    row_cap = int(mcp_cfg.get("max_rows", 1000))
                    if len(data) > row_cap:
                        print(f"⚡ [MCP] Row cap applied: {len(data)} → {row_cap}")
                        data = data[:row_cap]

                return {
                    "sql": sql_query,
                    "columns": columns,
                    "data": data,
                    "explanation": explanation,
                    "row_cap_applied": row_cap if row_cap and len(data) == row_cap else None,
                    "query_id": None
                }

            else:
                enhanced_question = question
                if conversation_id:
                    conv_context = conversation_manager.get_conversation_context(conversation_id)
                    if len(conv_context) > 1:
                        context_text = "Previous conversation:\n"
                        for msg in conv_context[-5:]:
                            role_label = "User" if msg['role'] == 'user' else "Assistant"
                            context_text += f"{role_label}: {msg['content']}\n"
                        enhanced_question = f"{context_text}\n\nCurrent question: {question}"
                        print(f"💬 Chat with context ({len(conv_context)} messages)")

                # Generate chat response with task-routed model
                chat_response = llm_chat.generate_chat_response(enhanced_question, schema_info)
                if audit_log_db and session_id:
                    _u = getattr(llm_chat, "last_token_usage", {})
                    audit_log_db.log(
                        session_id=session_id, operation_type="chat_response",
                        model_name=llm_chat.get_model_name(), question=question,
                        prompt_preview=enhanced_question[:500],
                        input_tokens=_u.get("input_tokens", 0),
                        output_tokens=_u.get("output_tokens", 0),
                        user_id=user_id, widget_type="auth",
                    )

                return {
                    "response_type": "chat",
                    "message": chat_response,
                    "intent_info": intent_result
                }

        except Exception as e:
            print(f"❌ Query execution error: {e}")
            import traceback
            traceback.print_exc()

            return {
                "response_type": "chat",
                "message": f"❌ Error executing query: {str(e)}",
                "error": True
            }

    def shutdown(self) -> None:
        """Cleanup on shutdown"""
        print("🔐 Shutting down Enhanced Auth Plugin...")
        self.session_manager.stop_cleanup_task()
        self.executor.shutdown(wait=True)


def create_auth_plugin(config: Dict[str, Any]) -> AuthPlugin:
    """
    Factory function to create auth plugin (backward compatible)
    """
    return AuthPlugin(config)