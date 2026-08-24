"""
SQLatte Authentication Plugin - Enhanced Version (Backward Compatible)
With all standard widget features + config-based restrictions
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Dict, Any, List
import asyncio
import ipaddress
import json
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
    # Both default to None (not e.g. 'default') so omitting them from the
    # request — the unified sign-in form no longer collects catalog/schema
    # for Trino — produces a catalog-less session rather than an
    # accidental single-catalog one. See AuthPlugin.register_routes'
    # /auth/login for how that's then scoped by allowed_catalogs.
    catalog: Optional[str] = None
    schema: Optional[str] = None
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
        # Block SSRF via private/loopback/link-local IP addresses
        try:
            addr = ipaddress.ip_address(v)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise ValueError("host resolves to a reserved or private address")
        except ValueError as exc:
            if "reserved" in str(exc) or "private" in str(exc):
                raise
            # v is a hostname (not a bare IP) — format already validated above
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

        # Normalized {catalog: [allowed_schema, ...]} used to let discovery
        # tokens run restricted ask_database queries (see
        # catalog_allowlist_violation) — always a dict, even when the
        # deployment used the old flat allowed_catalogs list (those catalogs
        # then allow any schema). Empty means nothing is configured to allow,
        # which /auth/query treats as "discovery tokens stay query-less".
        if self.catalog_schema_map:
            self._discovery_query_catalog_map = self.catalog_schema_map
        elif self.allowed_catalogs:
            self._discovery_query_catalog_map = {c: [] for c in self.allowed_catalogs}
        else:
            self._discovery_query_catalog_map = {}
        self.db_provider = config.get('db_provider', None)  # Optional
        self.db_host = config.get('db_host', None)  # Optional
        self.db_port = config.get('db_port', None)  # Optional
        # Trino-only: reject generated SQL that references a catalog other
        # than the session's own. On by default — set to false in config.yaml
        # (plugins.auth.enforce_catalog_lock: false) to turn it back off
        # without a code change if it turns out too strict somewhere.
        self.enforce_catalog_lock = config.get('enforce_catalog_lock', True)
        # Cross-catalog discovery tokens/endpoints — off by default, still
        # settling in. Set true in config.yaml (plugins.auth.enable_discovery_tokens)
        # to turn on. Gates /auth/discovery-token, /auth/discover,
        # /auth/token/generate-discovery, the admin /discovery-token endpoint,
        # and the MCP discover_tables tool.
        self.enable_discovery_tokens = config.get('enable_discovery_tokens', False)

        # _get_tables_for_session() instantiates a brand-new DatabaseProvider
        # (and, for BigQuery, re-enumerates every table in the dataset) on
        # every single call — fine for Trino, but a 30s+ round trip for a
        # BigQuery dataset with many tables. Cache the result briefly, keyed
        # by db_config (auto-sessions all share the same server-configured
        # db_config, so they share one cache entry; distinct manual-login
        # configs each get their own).
        self._tables_cache: Dict[str, Dict[str, Any]] = {}
        self._TABLES_CACHE_TTL_SECONDS = 300

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
                "db_port": self.db_port,
                "discovery_enabled": self.enable_discovery_tokens,
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
                # A Trino login with no catalog is intentional now — the token
                # screen no longer asks for one (see tokens.html). Visibility
                # for that session is governed entirely by allowed_catalogs at
                # query/discover/describe time instead of at login, so the
                # catalog/schema allowlist check below only applies when the
                # caller actually supplied one (e.g. a legacy client, or a
                # non-Trino provider where this model doesn't apply).
                is_catalog_less_trino = request.database_type == 'trino' and not request.catalog

                # Deployments that haven't turned on discovery
                # (plugins.auth.enable_discovery_tokens) don't get the
                # catalog-less model either — tokens.html only omits the
                # catalog field when discovery_enabled is true (see
                # /auth/config), but guard the endpoint itself too against a
                # client built for an older/differently-configured server.
                if is_catalog_less_trino and not self.enable_discovery_tokens:
                    raise HTTPException(
                        status_code=400,
                        detail="This server requires a catalog for Trino logins "
                               "(plugins.auth.enable_discovery_tokens is off)."
                    )

                if not is_catalog_less_trino:
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

                # Test connection in thread pool (non-blocking). A catalog-less
                # Trino login can't use the usual SHOW TABLES probe (fails with
                # MISSING_CATALOG_NAME) — just open the connection instead, same
                # check the old discovery-token flow used.
                loop = asyncio.get_event_loop()
                if is_catalog_less_trino:
                    is_valid = await loop.run_in_executor(
                        self.executor,
                        self._test_trino_discovery_connection,
                        db_config
                    )
                else:
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

        @app.post("/auth/discovery-token")
        async def create_discovery_token_direct(request: dict, http_request: Request):
            """
            Issue a Trino discovery token directly from username/password —
            no catalog/schema, no prior session. Same shape as /auth/login
            (server-configured host/port, brute-force protection) but skips
            the catalog allowlist entirely since discovery is cross-catalog
            by design, and returns the token immediately instead of a session.
            """
            if not self.enable_discovery_tokens:
                raise HTTPException(404, "Discovery tokens are disabled on this server.")

            if self.db_provider != "trino":
                raise HTTPException(
                    400,
                    f"Discovery tokens are Trino-only — this server is configured for '{self.db_provider}'."
                )

            ip = _client_ip(http_request)
            _check_login_allowed(ip)

            username = (request.get("username") or "").strip()
            password = request.get("password") or ""
            if not username or not password:
                raise HTTPException(400, "username and password are required")

            trino_config = {
                "host": self.db_host,
                "port": self.db_port,
                "user": username,
                "password": password,
                "http_scheme": "https",
            }

            try:
                loop = asyncio.get_event_loop()
                is_valid = await loop.run_in_executor(
                    self.executor, self._test_trino_discovery_connection, trino_config
                )
                if not is_valid:
                    _record_failed_login(ip)
                    raise HTTPException(401, "Invalid credentials or connection failed")

                from src.core.config_db import get_config_db
                ttl_hours = int(request.get("ttl_hours", 24))
                description = request.get("description", "Discovery Token")
                token = get_config_db().create_discovery_token(
                    username=username,
                    trino_config=trino_config,
                    ttl_hours=ttl_hours,
                    description=description,
                )

                _clear_login_attempts(ip)
                return {
                    "success": True,
                    "token": token,
                    "ttl_hours": ttl_hours,
                    "message": f"Discovery token valid for {ttl_hours}h. discover_tables always works; "
                               f"ask_database works too if the server has allowed_catalogs configured "
                               f"(fully-qualified tables only).",
                }
            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Discovery token error: {e}")
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
            """
            Get available tables for authenticated user.

            A catalog-less session (see _config_catalog) has no single
            catalog for SHOW TABLES to run against — instead of erroring,
            fall back to discover_tables with an empty search_term (see
            TrinoProvider.discover_tables), restricted to allowed_catalogs,
            and hand back fully-qualified catalog.schema.table names. Same
            metadata call as /auth/discover, so it draws from the same
            discover budget.
            """
            try:
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

                loop = asyncio.get_event_loop()

                if self._config_catalog(session.db_config) is None:
                    if not self._discovery_query_catalog_map:
                        raise HTTPException(
                            403,
                            "This token has no default catalog and this server has no "
                            "allowed_catalogs configured to list tables from. Ask an admin "
                            "to set plugins.auth.allowed_catalogs."
                        )
                    if session.api_token:
                        from src.core.config_db import get_config_db
                        budget = get_config_db().consume_token_discover_budget(session.api_token)
                        if budget is None:
                            raise HTTPException(401, "API token expired or revoked")
                        if budget.get("_error") == "budget_exceeded":
                            raise HTTPException(
                                429,
                                f"Daily discover budget of {budget['daily_limit']} calls exceeded. "
                                f"Resets at midnight UTC."
                            )

                    result = await loop.run_in_executor(
                        self.executor,
                        self._discover_tables_for_session,
                        session.db_config,
                        "",
                    )
                    tables = [f"{m['catalog']}.{m['schema']}.{m['table']}" for m in result.get("matches", [])]
                else:
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

        @app.post("/auth/discover")
        async def discover_tables(request: dict, session_id: str = Header(..., alias="X-Session-ID")):
            """
            Cross-catalog table/collection name search — metadata only, no
            row data. Works for query tokens too (harmless, same data a
            SHOW/DESCRIBE could already surface), but this is the whole
            point of discovery tokens, which have no catalog/schema of
            their own to fall back on.
            """
            if not self.enable_discovery_tokens:
                raise HTTPException(404, "Discovery is disabled on this server.")

            try:
                session = self.session_manager.get_session(session_id)
                if not session:
                    raise HTTPException(401, "Session expired or invalid")

                # Enforce the token's daily discover budget, if this session
                # came from one — same pattern as /auth/query's query budget,
                # just a separate counter (see consume_token_discover_budget).
                if session.api_token:
                    from src.core.config_db import get_config_db
                    budget = get_config_db().consume_token_discover_budget(session.api_token)
                    if budget is None:
                        raise HTTPException(401, "API token expired or revoked")
                    if budget.get("_error") == "budget_exceeded":
                        raise HTTPException(
                            429,
                            f"Daily discover budget of {budget['daily_limit']} calls exceeded. "
                            f"Resets at midnight UTC."
                        )

                # Empty search_term means "list everything (within
                # allowed_catalogs, if configured)" — this is also what
                # /auth/tables falls back to for a catalog-less session, so
                # both share this one code path instead of a separate
                # per-catalog SHOW TABLES loop.
                search_term = (request.get("search_term") or "").strip()

                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    self._discover_tables_for_session,
                    session.db_config,
                    search_term,
                )
                return result

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Error discovering tables: {e}")
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

        @app.get("/auth/mcp-mask-rules")
        async def get_mcp_mask_rules(session_id: str = Header(..., alias="X-Session-ID")):
            """Return enabled MCP field masking rules (readable by any valid session)."""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(401, "Session expired or invalid")
            from src.core.config_db import get_config_db
            rules = get_config_db().list_mask_rules()
            active = [
                {"field_pattern": r["field_pattern"], "strategy": r["strategy"]}
                for r in rules if r["enabled"]
            ]
            return {"rules": active}

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

                # 1a. A catalog-less session (no default catalog — old
                # discovery tokens, and every token minted since the token
                # screen stopped collecting a catalog) has no single scope of
                # its own, so ask_database is only allowed when the
                # deployment has an allowlist configured
                # (plugins.auth.allowed_catalogs) — the query gets checked
                # against it below via catalog_allowlist_violation instead of
                # the usual single-catalog catalog_violation lock. No
                # allowlist means nothing is safe to permit, so it stays
                # metadata-only. Driven by the session's actual db_config
                # (see _config_catalog), not by token_type, so this covers a
                # legacy 'query' token exactly as it always has (it carries a
                # fixed catalog, so it never hits this branch) alongside
                # every catalog-less token regardless of type.
                token_type = getattr(session, "token_type", "query")
                is_catalog_less = self._config_catalog(session.db_config) is None
                if is_catalog_less and not self._discovery_query_catalog_map:
                    raise HTTPException(
                        403,
                        "This token has no default catalog (catalog/table search only) and "
                        "this server has no allowed_catalogs configured to run restricted "
                        "queries against. Use a token with a default catalog for ask_database, "
                        "or ask an admin to set plugins.auth.allowed_catalogs."
                    )

                # 1b. Enforce the token's daily query budget, if this session came from one
                if session.api_token:
                    from src.core.config_db import get_config_db
                    budget = get_config_db().consume_token_query_budget(session.api_token)
                    if budget is None:
                        raise HTTPException(401, "API token expired or revoked")
                    if budget.get("_error") == "budget_exceeded":
                        raise HTTPException(
                            429,
                            f"Daily query budget of {budget['daily_limit']} queries exceeded. "
                            f"Resets at midnight UTC."
                        )

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
                    token_type,
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

                raw_discover_limit = request.get("daily_discover_limit")
                daily_discover_limit = int(raw_discover_limit) if raw_discover_limit not in (None, "", 0, "0") else None

                token = config_db.create_api_token(
                    username=session.username,
                    db_config=session.db_config,
                    ttl_hours=ttl_hours,
                    description=description,
                    daily_query_limit=daily_query_limit,
                    daily_discover_limit=daily_discover_limit,
                )

                platform_default = config_db.get_default_token_limit()
                if daily_query_limit is None:
                    effective_limit = platform_default
                elif platform_default is not None:
                    effective_limit = min(daily_query_limit, platform_default)
                else:
                    effective_limit = daily_query_limit

                discover_platform_default = config_db.get_default_discover_limit()
                if daily_discover_limit is None:
                    effective_discover_limit = discover_platform_default
                elif discover_platform_default is not None:
                    effective_discover_limit = min(daily_discover_limit, discover_platform_default)
                else:
                    effective_discover_limit = daily_discover_limit

                limit_str = f"{effective_limit} queries/day" if effective_limit is not None else "unlimited"
                discover_limit_str = f"{effective_discover_limit} discover calls/day" if effective_discover_limit is not None else "unlimited discover calls"
                return {
                    "success": True,
                    "token": token,
                    "ttl_hours": ttl_hours,
                    "description": description,
                    "daily_query_limit": effective_limit,
                    "daily_discover_limit": effective_discover_limit,
                    "message": f"Token valid for {ttl_hours} hours, {limit_str}, {discover_limit_str}. Set SQLATTE_TOKEN in your MCP config.",
                }
            except Exception as e:
                print(f"❌ Token generate error: {e}")
                raise server_error(e)

        @app.post("/auth/token/generate-discovery")
        async def generate_discovery_token(
            request: dict,
            session_id: str = Header(..., alias="X-Session-ID")
        ):
            """
            Generate a discovery token from an active session — reuses the
            session's already-validated Trino credentials (host/user/
            password). Trino only.

            discover_tables always works. ask_database also works, restricted
            to fully-qualified tables within plugins.auth.allowed_catalogs
            (see AuthPlugin._config_catalog and
            sql_validator.catalog_allowlist_violation); with no
            allowed_catalogs configured it stays blocked. Since the token
            screen (tokens.html) now signs in catalog-less by default when
            discovery is enabled, /auth/token/generate produces the same
            shape of token — this endpoint is kept for direct/API callers
            that still want an explicitly-labeled "discovery" token.
            """
            if not self.enable_discovery_tokens:
                raise HTTPException(404, "Discovery tokens are disabled on this server.")

            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(401, "Session expired or invalid")

            if session.db_config.get("provider") != "trino":
                raise HTTPException(
                    400,
                    "Discovery tokens are Trino-only — this session's provider is "
                    f"'{session.db_config.get('provider')}'."
                )

            try:
                from src.core.config_db import get_config_db
                config_db = get_config_db()

                ttl_hours = int(request.get("ttl_hours", 24))
                description = request.get("description", "Discovery Token")

                token = config_db.create_discovery_token(
                    username=session.username,
                    trino_config=session.db_config["trino"],
                    ttl_hours=ttl_hours,
                    description=description,
                )

                return {
                    "success": True,
                    "token": token,
                    "ttl_hours": ttl_hours,
                    "description": description,
                    "message": f"Discovery token valid for {ttl_hours} hours. discover_tables always works; "
                               f"ask_database works too if the server has allowed_catalogs configured "
                               f"(fully-qualified tables only).",
                }
            except Exception as e:
                print(f"❌ Discovery token generate error: {e}")
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

                new_session_id = self.session_manager.create_session(
                    username=result["username"],
                    db_config=result["db_config"],
                    api_token=token,
                    token_type=result.get("token_type", "query"),
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

    @staticmethod
    def _config_catalog(db_config: Dict[str, Any]) -> Optional[str]:
        """
        The "single scope" a session/token's db_config is locked to, or None
        if it has none — a Trino connection with no catalog set (a
        catalog-less, discovery-shaped session) being the only case that
        currently produces None. Used as the single source of truth for
        "does this session need the allowlist (catalog_allowlist_violation /
        qualified_table_allowlist_violation) or the old single-catalog lock
        (catalog_violation)?" — driven by what the connection actually is,
        not by token_type, so it naturally covers old and new tokens alike
        without a migration: a legacy 'query' token still carries a fixed
        catalog and keeps the single-catalog behavior; a legacy 'discovery'
        token, and every token minted since catalog selection was removed
        from the token screen, has none and gets the allowlist behavior.
        """
        prov = db_config.get("provider", "")
        sub = db_config.get(prov, {}) or {}
        return sub.get("catalog") or sub.get("project_id") or sub.get("database") or None

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

    def _test_trino_discovery_connection(self, trino_config: Dict[str, Any]) -> bool:
        """
        Credential check for the catalog-less discovery-token flow.

        Unlike _test_db_connection (which runs SHOW TABLES and therefore
        requires a session catalog/schema), this only opens a connection —
        SHOW TABLES fails with MISSING_CATALOG_NAME when no catalog is set,
        which discovery tokens intentionally never set.
        """
        from src.providers.database.trino_provider import TrinoProvider
        try:
            return TrinoProvider(trino_config).health_check()
        except Exception as e:
            print(f"❌ Discovery connection test failed: {e}")
            return False

    def _get_tables_for_session(self, db_config: Dict[str, Any]) -> List[str]:
        """Get tables for a session's DB connection (cached — see __init__)"""
        cache_key = json.dumps(db_config, sort_keys=True, default=str)
        cached = self._tables_cache.get(cache_key)
        now = time.time()
        if cached and now - cached["ts"] <= self._TABLES_CACHE_TTL_SECONDS:
            return cached["tables"]

        try:
            wrapped_config = {'database': db_config}
            db_provider = ProviderFactory.create_db_provider(wrapped_config)
            tables = db_provider.get_tables()

            print(f"📊 Retrieved {len(tables)} tables")
            self._tables_cache[cache_key] = {"ts": now, "tables": tables}
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
        """
        Get schema for a specific table (DESCRIBE).

        A session with a fixed catalog (see _config_catalog) is implicitly
        scoped by the connection itself, same as it always has been — no
        extra check needed. A catalog-less session has no such connection-
        level scope, so describe is gated the same way ask_database is:
        table_name must be fully qualified as catalog.schema.table and that
        catalog+schema must be in the allowlist (plugins.auth.allowed_catalogs)
        — see qualified_table_allowlist_violation. Applies to old discovery
        tokens and every token minted since catalog selection was removed
        from the token screen alike.
        """
        if self._config_catalog(db_config) is None and db_config.get("provider") == "trino":
            if not self._discovery_query_catalog_map:
                raise HTTPException(
                    403,
                    "This token has no default catalog and this server has no "
                    "allowed_catalogs configured to describe tables against. Ask an "
                    "admin to set plugins.auth.allowed_catalogs."
                )
            from src.core.sql_validator import qualified_table_allowlist_violation
            violation = qualified_table_allowlist_violation(table_name, self._discovery_query_catalog_map)
            if violation:
                raise HTTPException(403, violation)

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

    def _discover_tables_for_session(
        self,
        db_config: Dict[str, Any],
        search_term: str,
    ) -> Dict[str, Any]:
        """
        Cross-catalog table/collection search (Trino only — see
        DatabaseProvider.discover_tables), always restricted server-side to
        self._discovery_query_catalog_map when it's configured — narrower
        than "every catalog this DB user can see", which is both more
        relevant to hand back and keeps a catalog-less token from ever
        seeing metadata for catalogs it isn't allowed to query anyway.
        """
        try:
            wrapped_config = {'database': db_config}
            db_provider = ProviderFactory.create_db_provider(wrapped_config)
            result = db_provider.discover_tables(search_term, self._discovery_query_catalog_map)

            print(f"🔎 Discovery '{search_term}': {len(result.get('matches', []))} matches")
            return result

        except NotImplementedError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            print(f"❌ Discovery failed for '{search_term}': {e}")
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
            token_type: str = "query",
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

                from src.core.sql_validator import is_select_only, violation_reason, risk_score, dialect_for_provider, catalog_violation, catalog_allowlist_violation
                _prov = db_config.get("provider", "")
                _dialect = dialect_for_provider(_prov)
                _sql_valid = is_select_only(sql_query, dialect=_dialect)
                _risk = risk_score(sql_query, dialect=_dialect)
                _u = getattr(llm_sql, "last_token_usage", {})
                _full_tables = [
                    line.replace("Table:", "").strip()
                    for line in schema_info.split("\n")
                    if line.startswith("Table:")
                ]
                _catalog = self._config_catalog(db_config)
                _widget = "mcp" if bypass_intent else "auth"

                if not _sql_valid:
                    reason = violation_reason(sql_query, dialect=_dialect)
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

                if self.enforce_catalog_lock:
                    # A catalog-less session (no default catalog — see
                    # _config_catalog) has no single catalog of its own (see
                    # /auth/query's is_catalog_less check above, which already
                    # refused to get here at all if _discovery_query_catalog_map
                    # is empty) — check every table ref against the allowlist
                    # instead of locking to one catalog. Driven by _catalog
                    # itself rather than token_type, so this applies to any
                    # catalog-less token, old or new, regardless of how it was
                    # created.
                    if not _catalog:
                        _cat_reason = catalog_allowlist_violation(
                            sql_query, _dialect, self._discovery_query_catalog_map
                        )
                    else:
                        _cat_reason = catalog_violation(sql_query, _dialect, _catalog)
                    if _cat_reason:
                        print(f"🚫 Blocked cross-catalog query (auth): {_cat_reason} | SQL: {sql_query[:120]}")
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
                            "reason": _cat_reason,
                            "message": _cat_reason,
                        }

                # Execute — unless query.execute_generated_sql is off. MCP calls
                # (bypass_intent) always execute regardless: they're a
                # programmatic tool contract, not the interactive assistant.
                _execute_sql = bypass_intent or llm_config.get("query", {}).get("execute_generated_sql", True)

                import time as _time
                if _execute_sql:
                    _exec_start = _time.time()
                    columns, data = db_provider.execute_query(sql_query)
                    _execution_ms = int((_time.time() - _exec_start) * 1000)
                    print(f"✅ Query executed: {len(data)} rows returned")
                else:
                    columns, data = [], []
                    _execution_ms = 0
                    print("⏭️  [Auth] Execution skipped (query.execute_generated_sql=false) — SQL generated only")

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

                from src.core.security_alerts import check_and_alert
                check_and_alert(
                    sql=sql_query,
                    risk_score=_risk,
                    username=user_id,
                    session_id=session_id or "",
                    catalog=_catalog,
                    widget_type=_widget,
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
                    "query_id": None,
                    "execution_skipped": not _execute_sql
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