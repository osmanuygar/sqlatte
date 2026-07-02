"""
SQLatte MCP SSE Server — embedded in the FastAPI app.

Mounts at /mcp:
  GET  /mcp/sse          → SSE connection (clients connect here)
  POST /mcp/messages/    → message endpoint (MCP protocol)

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
    return [
        types.Tool(
            name="ask_database",
            description=(
                "Ask a question in natural language about data in a specific table. "
                "SQLatte translates it to SQL, runs it, and returns results. "
                "Always provide table_name — call list_tables first if unknown."
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
            description="List all available tables in the connected catalog/schema.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_schema",
            description="Get column definitions for a specific table.",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                },
                "required": ["table_name"],
            },
        ),
    ]


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

        elif name == "get_schema":
            result = await _api("get", f"/auth/schema/{arguments['table_name']}")
            return [types.TextContent(type="text", text=result.get("schema", str(result)))]

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    except httpx.HTTPStatusError as e:
        return [types.TextContent(type="text", text=f"API error {e.response.status_code}: {e.response.text}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]


# ── SSE connection handler ────────────────────────────────────────────────────

def _get_self_url() -> str:
    try:
        from src.core.config_manager_enhanced import config_manager
        cfg = config_manager.get_config()
        port = cfg.get("app", {}).get("port", 8000)
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:8000"


async def handle_sse(request: Request) -> Response:
    # Token from header or query param
    token = request.headers.get("x-mcp-token") or request.query_params.get("token")
    if not token:
        return Response("Missing x-mcp-token header or ?token= query param", status_code=401)

    # Validate token and create a session — direct DB call, no HTTP
    try:
        from src.core.config_db import get_config_db
        from src.plugins.session_manager import auth_session_manager

        config_db = get_config_db()
        result = config_db.validate_api_token(token)

        if result is None:
            return Response("Invalid, expired, or revoked token", status_code=401)
        if result.get("_error") == "budget_exceeded":
            return Response(
                f"Daily query budget of {result['daily_limit']} exceeded. Resets at midnight UTC.",
                status_code=429,
            )

        session_id = auth_session_manager.create_session(
            username=result["username"],
            db_config=result["db_config"],
        )
        provider = result["db_config"].get("provider", "")
        sql_dialect = _PROVIDER_TO_DIALECT.get(provider, "")
    except Exception as e:
        logger.error(f"MCP SSE auth error: {e}")
        return Response("Authentication error", status_code=500)

    # Fetch active mask rules — direct DB call
    try:
        rules = [
            {"field_pattern": r["field_pattern"], "strategy": r["strategy"]}
            for r in config_db.list_mask_rules()
            if r["enabled"]
        ]
    except Exception:
        rules = []

    self_url = _get_self_url()

    # Set per-connection contextvars and run the MCP server for this connection
    _ctx_session_id.set(session_id)
    _ctx_self_url.set(self_url)
    _ctx_mask_rules.set(rules)
    _ctx_sql_dialect.set(sql_dialect)

    logger.info(f"MCP SSE connection: user={result['username']} session={session_id[:8]}...")

    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        # stateless=True: auth is handled above via token; skip the server-side
        # initialization state machine that causes race conditions when the MCP
        # client sends requests before notifications/initialized is processed.
        await server.run(streams[0], streams[1], server.create_initialization_options(), stateless=True)

    return Response()


# ── Starlette sub-app mounted at /mcp ─────────────────────────────────────────

mcp_app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ]
)
