"""
SQLatte MCP SSE Server — embedded in the FastAPI app.

Mounts at /mcp:
  GET  /mcp/sse          → SSE connection (clients connect here)
  POST /mcp/messages/    → message endpoint (MCP protocol)

Streamable HTTP (mcp.streamable_http.enabled, registered by app.py):
  POST /mcp/http         → stateless Streamable HTTP endpoint, for clients
                           that don't speak SSE (e.g. Microsoft Copilot Studio)

Client config (no local Python needed):
  {
    "mcpServers": {
      "sqlatte": {
        "url": "http://<host>:<port>/mcp/sse",
        "headers": { "x-mcp-token": "<token>" }
      }
    }
  }
"""

import contextvars
import fnmatch
import hashlib
import logging

import httpx
import sqlglot
from sqlglot import exp
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp import types
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

logger = logging.getLogger(__name__)

# ── Per-connection state (each SSE connection is isolated) ────────────────────
_ctx_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_session_id")
_ctx_self_url: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_self_url")
_ctx_mask_rules: contextvars.ContextVar[list] = contextvars.ContextVar("mcp_mask_rules", default=[])
_ctx_sql_dialect: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_sql_dialect", default="")

# DB provider name (config.yaml `database.provider`) → sqlglot dialect name
_PROVIDER_TO_DIALECT = {
    "bigquery": "bigquery",
    "mysql": "mysql",
    "postgresql": "postgres",
    "trino": "trino",
}

# ── MCP server instance (shared, stateless — state lives in contextvars) ──────
server = Server("sqlatte")

# ── SSE transport ─────────────────────────────────────────────────────────────
# DNS rebinding protection disabled — SQLatte handles its own auth via API tokens
_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
# endpoint path is relative to the mount point (/mcp), so just /messages/
sse = SseServerTransport("/messages/", security_settings=_security)

# ── Streamable HTTP transport ─────────────────────────────────────────────────
# Stateless + plain JSON responses: every POST is self-contained (the token is
# re-validated per request), so there's no MCP session to lose on a pod
# restart and no long-lived stream for the OKD route/HAProxy to time out.
# Its task group must be running — app.py enters mcp_http_manager.run() on
# startup.
mcp_http_manager = StreamableHTTPSessionManager(
    app=server,
    json_response=True,
    stateless=True,
    security_settings=_security,
)


# ── Internal API helper ───────────────────────────────────────────────────────

async def _api(method: str, path: str, **kwargs) -> dict:
    """Call the SQLatte API using this connection's session_id."""
    session_id = _ctx_session_id.get()
    self_url = _ctx_self_url.get()
    headers = kwargs.pop("headers", {})
    headers["X-Session-ID"] = session_id
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await getattr(client, method)(f"{self_url}{path}", headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json()


# ── Masking helpers ───────────────────────────────────────────────────────────

def _apply_mask(value: str, strategy: str) -> str:
    if strategy == "hash":
        return hashlib.sha256(str(value).encode()).hexdigest()[:16]
    if strategy == "partial":
        s = str(value)
        if "@" in s:
            local, domain = s.split("@", 1)
            return local[0] + "**@" + domain
        if len(s) <= 4:
            return "****"
        return s[0] + "*" * (len(s) - 2) + s[-1]
    return "[REDACTED]"


def _resolve_source_columns(sql: str) -> dict:
    """Map each output column (alias) to the real source column(s) it derives from.

    The LLM is free to alias a sensitive column to any name (e.g.
    `SELECT email AS contact_info`), which would let it slip past mask
    rules that only look at the displayed column name. Parsing the SQL
    lets us match rules against the underlying column instead of
    whatever name the query happened to give it.

    Best-effort: on any parse failure (unsupported dialect quirk, etc.)
    returns {} and callers fall back to matching on the display name,
    same as before this existed.
    """
    try:
        dialect = _ctx_sql_dialect.get() or None
        parsed = sqlglot.parse_one(sql, dialect=dialect)
        select = parsed if isinstance(parsed, exp.Select) else parsed.find(exp.Select)
        if select is None:
            return {}
        mapping = {}
        for projection in select.expressions:
            alias = (projection.alias_or_name or "").lower()
            cols = [c.name.lower() for c in projection.find_all(exp.Column)]
            if alias and cols:
                mapping[alias] = cols
        return mapping
    except Exception:
        return {}


def _mask_col(col: str, value, rules: list, source_map: dict):
    if value is None or value == "":
        return value
    col_lower = col.lower()
    # Match against every real source column feeding this output (covers
    # simple aliasing and multi-column expressions like CONCAT(a, b));
    # fall back to the display name itself if we couldn't resolve it.
    candidates = source_map.get(col_lower) or [col_lower]
    for rule in rules:
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, rule["field_pattern"]):
                return _apply_mask(value, rule["strategy"])
    return value


# ── Result formatter ──────────────────────────────────────────────────────────

def _format_result(result: dict) -> str:
    rules = _ctx_mask_rules.get()
    parts = []

    sql = result.get("sql") or result.get("generated_sql")
    if sql:
        parts.append(f"**Generated SQL:**\n```sql\n{sql}\n```")

    source_map = _resolve_source_columns(sql) if sql else {}

    data = result.get("data") or result.get("results")
    columns = result.get("columns")

    if data and columns:
        header = " | ".join(columns)
        sep = " | ".join(["---"] * len(columns))
        rows = "\n".join(
            " | ".join(str(_mask_col(columns[i], v, rules, source_map)) for i, v in enumerate(row))
            for row in data[:50]
        )
        parts.append(f"**Results ({len(data)} rows):**\n{header}\n{sep}\n{rows}")
        if len(data) > 50:
            parts.append(f"_(showing 50 of {len(data)} rows)_")
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        cols = list(data[0].keys())
        header = " | ".join(cols)
        sep = " | ".join(["---"] * len(cols))
        rows = "\n".join(
            " | ".join(str(_mask_col(c, r.get(c, ""), rules, source_map)) for c in cols)
            for r in data[:50]
        )
        parts.append(f"**Results ({len(data)} rows):**\n{header}\n{sep}\n{rows}")

    summary = result.get("summary") or result.get("message")
    if summary:
        parts.append(f"**Summary:** {summary}")

    if result.get("row_cap_applied"):
        parts.append(f"_Results capped at {result['row_cap_applied']} rows by server._")

    return "\n\n".join(parts)


# ── MCP tool definitions ──────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    try:
        discovery_enabled = (await _api("get", "/auth/config")).get("discovery_enabled", False)
    except Exception:
        discovery_enabled = False

    tools = [
        types.Tool(
            name="ask_database",
            description=(
                "Ask a question in natural language about data in a specific table. "
                "SQLatte translates it to SQL, runs it, and returns results. "
                "Always provide table_name — call list_tables first if unknown. If this "
                "is a catalog-less token, list_tables/discover_tables return fully-"
                "qualified catalog.schema.table names — pass one of those as table_name; "
                "queries are then restricted to the server's allowed catalogs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "table_name": {"type": "string"},
                    "table_schema": {"type": "string"},
                },
                "required": ["question", "table_name"],
            },
        ),
        types.Tool(
            name="list_tables",
            description=(
                "List available tables. For a token with a default catalog, lists "
                "the connected catalog/schema. For a catalog-less token, lists every "
                "table in the server's allowed catalogs instead, as fully-qualified "
                "catalog.schema.table names."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_schema",
            description=(
                "Get column definitions for a specific table. For a catalog-less "
                "token, table_name must be fully qualified as catalog.schema.table "
                "(from list_tables/discover_tables) and restricted to the server's "
                "allowed catalogs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                },
                "required": ["table_name"],
            },
        ),
    ]

    if discovery_enabled:
        tools.insert(2, types.Tool(
            name="discover_tables",
            description=(
                "Search table/collection names across allowed catalogs (not just the "
                "connected one, if any) by a partial name match — e.g. find which "
                "catalog and schema a table like 'couponcampaign' actually lives in "
                "before querying it. Omit search_term (or pass an empty string) to "
                "list everything instead of searching. Trino only; metadata only, "
                "returns no row data. Works with any token — including ask_database "
                "on a catalog-less token, which requires the fully-qualified "
                "catalog.schema.table this returns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Partial table/collection name to search for, e.g. 'campaign'. Omit or leave empty to list everything.",
                    },
                },
            },
        ))

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "ask_database":
            table_name = arguments.get("table_name", "")
            table_schema = arguments.get("table_schema", "")
            if table_name and not table_schema:
                schema_result = await _api("get", f"/auth/schema/{table_name}")
                table_schema = schema_result.get("schema", "")
            result = await _api("post", "/auth/query", json={
                "question": arguments["question"],
                "table_schema": table_schema,
                "bypass_intent": True,
            })
            # Fetch fresh mask rules on every query — local PG, ~1ms, negligible vs LLM+DB
            try:
                from src.core.config_db import get_config_db
                fresh_rules = [
                    {"field_pattern": r["field_pattern"], "strategy": r["strategy"]}
                    for r in get_config_db().list_mask_rules() if r["enabled"]
                ]
                _ctx_mask_rules.set(fresh_rules)
            except Exception:
                pass
            return [types.TextContent(type="text", text=_format_result(result))]

        elif name == "list_tables":
            result = await _api("get", "/auth/tables")
            tables = result.get("tables", [])
            return [types.TextContent(type="text", text="\n".join(tables) or "No tables found.")]

        elif name == "discover_tables":
            search_term = arguments.get("search_term", "")
            result = await _api("post", "/auth/discover", json={
                "search_term": search_term,
            })
            matches = result.get("matches", [])
            if not matches:
                label = f"matching '{search_term}'" if search_term else "in any allowed catalog"
                return [types.TextContent(type="text", text=f"No tables found {label}.")]
            lines = [f"{m['catalog']}.{m['schema']}.{m['table']}" for m in matches]
            text = f"**Matches ({len(matches)}):**\n" + "\n".join(lines)
            columns_by_table = result.get("columns", {})
            if columns_by_table:
                text += "\n\n**Columns (top matches):**"
                for table_ref, cols in columns_by_table.items():
                    text += f"\n\n`{table_ref}`:\n" + "\n".join(f"- {c}" for c in cols)
            return [types.TextContent(type="text", text=text)]

        elif name == "get_schema":
            result = await _api("get", f"/auth/schema/{arguments['table_name']}")
            return [types.TextContent(type="text", text=result.get("schema", str(result)))]

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    except httpx.HTTPStatusError as e:
        return [types.TextContent(type="text", text=f"API error {e.response.status_code}: {e.response.text}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]


# ── Connection auth & context (shared by SSE and Streamable HTTP) ─────────────

def _get_self_url() -> str:
    try:
        from src.core.config_manager_enhanced import config_manager
        cfg = config_manager.get_config()
        port = cfg.get("app", {}).get("port", 8000)
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:8000"


class _AuthError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _request_token(request: Request) -> str | None:
    return request.headers.get("x-mcp-token") or request.query_params.get("token")


def _validate_token(token: str | None) -> dict:
    """Validate an API token — direct DB call, no HTTP. Raises _AuthError."""
    if not token:
        raise _AuthError(401, "Missing x-mcp-token header or ?token= query param")
    try:
        from src.core.config_db import get_config_db
        result = get_config_db().validate_api_token(token)
    except Exception as e:
        logger.error(f"MCP auth error: {e}")
        raise _AuthError(500, "Authentication error")
    if result is None:
        raise _AuthError(401, "Invalid, expired, or revoked token")
    return result


def _create_session(token: str, token_info: dict) -> str:
    try:
        from src.plugins.session_manager import auth_session_manager
        return auth_session_manager.create_session(
            username=token_info["username"],
            db_config=token_info["db_config"],
            api_token=token,
            token_type=token_info.get("token_type", "query"),
        )
    except Exception as e:
        logger.error(f"MCP session creation error: {e}")
        raise _AuthError(500, "Authentication error")


def _load_mask_rules() -> list:
    """Fetch active mask rules — direct DB call."""
    try:
        from src.core.config_db import get_config_db
        return [
            {"field_pattern": r["field_pattern"], "strategy": r["strategy"]}
            for r in get_config_db().list_mask_rules()
            if r["enabled"]
        ]
    except Exception:
        return []


def _set_request_context(session_id: str, token_info: dict) -> None:
    """Set the per-connection contextvars the tool handlers read."""
    provider = token_info["db_config"].get("provider", "")
    _ctx_session_id.set(session_id)
    _ctx_self_url.set(_get_self_url())
    _ctx_mask_rules.set(_load_mask_rules())
    _ctx_sql_dialect.set(_PROVIDER_TO_DIALECT.get(provider, ""))


# ── SSE connection handler ────────────────────────────────────────────────────

async def handle_sse(request: Request) -> Response:
    token = _request_token(request)
    try:
        token_info = _validate_token(token)
        session_id = _create_session(token, token_info)
    except _AuthError as e:
        return Response(e.message, status_code=e.status_code)

    _set_request_context(session_id, token_info)

    logger.info(f"MCP SSE connection: user={token_info['username']} session={session_id[:8]}...")

    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        # stateless=True: auth is handled above via token; skip the server-side
        # initialization state machine that causes race conditions when the MCP
        # client sends requests before notifications/initialized is processed.
        await server.run(streams[0], streams[1], server.create_initialization_options(), stateless=True)

    return Response()


# ── Streamable HTTP handler ───────────────────────────────────────────────────

# sha256(token) → auth session_id. Streamable HTTP is stateless, so without
# this every tool call would mint a fresh auth session; reusing one per token
# keeps the session list (and the conversation link on it) stable. The token
# itself is still re-validated on every request, so revocation is immediate.
_http_sessions: dict[str, str] = {}


def _session_for_token(token: str, token_info: dict) -> str:
    from src.plugins.session_manager import auth_session_manager

    key = hashlib.sha256(token.encode()).hexdigest()
    session_id = _http_sessions.get(key)
    if session_id and auth_session_manager.get_session(session_id):
        return session_id
    session_id = _create_session(token, token_info)
    _http_sessions[key] = session_id
    return session_id


class _StreamableHTTPEndpoint:
    """Raw ASGI endpoint (a class instance, so Starlette's Route passes it
    scope/receive/send instead of wrapping it as a request handler)."""

    async def __call__(self, scope, receive, send):
        request = Request(scope, receive)
        token = _request_token(request)
        try:
            token_info = _validate_token(token)
            session_id = _session_for_token(token, token_info)
        except _AuthError as e:
            await Response(e.message, status_code=e.status_code)(scope, receive, send)
            return

        # The manager runs the MCP server in a task spawned from this one, so
        # it inherits these contextvars.
        _set_request_context(session_id, token_info)
        await mcp_http_manager.handle_request(scope, receive, send)


mcp_http_endpoint = _StreamableHTTPEndpoint()


# ── Starlette sub-app mounted at /mcp ─────────────────────────────────────────

mcp_app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ]
)
