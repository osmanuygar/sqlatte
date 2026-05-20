#!/usr/bin/env python3
"""
SQLatte MCP Server

Exposes SQLatte's natural language SQL capabilities to Claude.
Configure via environment variables and add to Claude settings.

Setup:
    pip install mcp httpx

Claude settings.json:
    {
      "mcpServers": {
        "sqlatte": {
          "command": "python3",
          "args": ["/path/to/sqlatte_mcp_server.py"],
          "env": {
            "SQLATTE_URL": "http://localhost:8000",
            "TRINO_HOST": "your-trino-host",
            "TRINO_PORT": "443",
            "TRINO_USER": "your-username",
            "TRINO_PASSWORD": "your-password",
            "TRINO_CATALOG": "hive",
            "TRINO_SCHEMA": "default",
            "TRINO_HTTP_SCHEME": "https"
          }
        }
      }
    }
"""

import os
import asyncio
import json
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ── Config from environment ────────────────────────────────────────────────────
SQLATTE_URL   = os.environ.get("SQLATTE_URL", "http://localhost:8000").rstrip("/")
TRINO_HOST    = os.environ.get("TRINO_HOST", "")
TRINO_PORT    = int(os.environ.get("TRINO_PORT", "443"))
TRINO_USER    = os.environ.get("TRINO_USER", "")
TRINO_PASSWORD= os.environ.get("TRINO_PASSWORD", "")
TRINO_CATALOG = os.environ.get("TRINO_CATALOG", "hive")
TRINO_SCHEMA  = os.environ.get("TRINO_SCHEMA", "default")
TRINO_SCHEME  = os.environ.get("TRINO_HTTP_SCHEME", "https")

_session_id: str | None = None

# ── SQLatte API helpers ────────────────────────────────────────────────────────
async def _login() -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{SQLATTE_URL}/auth/login", json={
            "username":    TRINO_USER,
            "password":    TRINO_PASSWORD,
            "database_type": "trino",
            "host":        TRINO_HOST,
            "port":        TRINO_PORT,
            "catalog":     TRINO_CATALOG,
            "schema":      TRINO_SCHEMA,
            "http_scheme": TRINO_SCHEME,
        })
        resp.raise_for_status()
        data = resp.json()
        return data["session_id"]


async def _get_session() -> str:
    global _session_id
    if not _session_id:
        _session_id = await _login()
    return _session_id


async def _api(method: str, path: str, **kwargs) -> dict:
    """Call SQLatte API with auto-relogin on session expiry."""
    global _session_id
    sid = await _get_session()
    headers = kwargs.pop("headers", {})
    headers["X-Session-ID"] = sid

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await getattr(client, method)(
            f"{SQLATTE_URL}{path}", headers=headers, **kwargs
        )
        if resp.status_code == 401:
            _session_id = None
            sid = await _get_session()
            headers["X-Session-ID"] = sid
            resp = await getattr(client, method)(
                f"{SQLATTE_URL}{path}", headers=headers, **kwargs
            )
        resp.raise_for_status()
        return resp.json()

# ── MCP Server ─────────────────────────────────────────────────────────────────
server = Server("sqlatte")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="ask_database",
            description=(
                "Ask a question in natural language about data in a specific table. "
                "SQLatte translates it to SQL, runs it on Trino, and returns the results. "
                "IMPORTANT: Always provide table_name. If you don't know the table name, "
                "call list_tables first to discover available tables."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural language question, e.g. 'Show me top 10 users by spend last month'"
                    },
                    "table_name": {
                        "type": "string",
                        "description": "Table to query, e.g. 'orders' or 'sales.orders'. Call list_tables first if unknown."
                    },
                    "table_schema": {
                        "type": "string",
                        "description": "Optional: override auto-fetched schema with custom schema text"
                    }
                },
                "required": ["question", "table_name"]
            }
        ),
        types.Tool(
            name="list_tables",
            description="List all available tables in the connected Trino catalog/schema.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_schema",
            description="Get column definitions for a specific table.",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Table name, optionally schema-qualified (e.g. 'orders' or 'sales.orders')"
                    }
                },
                "required": ["table_name"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "ask_database":
            table_schema = arguments.get("table_schema", "")
            table_name = arguments.get("table_name", "")
            if table_name and not table_schema:
                schema_result = await _api("get", f"/auth/schema/{table_name}")
                table_schema = schema_result.get("schema", "")
            result = await _api("post", "/auth/query", json={
                "question":      arguments["question"],
                "table_schema":  table_schema,
                "bypass_intent": True,
            })
            return [types.TextContent(type="text", text=_format_query_result(result))]

        elif name == "list_tables":
            result = await _api("get", "/auth/tables")
            tables = result.get("tables", [])
            return [types.TextContent(type="text", text="\n".join(tables) if tables else "No tables found.")]

        elif name == "get_schema":
            table = arguments["table_name"]
            result = await _api("get", f"/auth/schema/{table}")
            schema = result.get("schema", str(result))
            return [types.TextContent(type="text", text=schema)]

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    except httpx.HTTPStatusError as e:
        return [types.TextContent(type="text", text=f"API error {e.response.status_code}: {e.response.text}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]


def _format_query_result(result: dict) -> str:
    parts = []

    sql = result.get("sql") or result.get("generated_sql")
    if sql:
        parts.append(f"**Generated SQL:**\n```sql\n{sql}\n```")

    data = result.get("data") or result.get("results")
    columns = result.get("columns")

    if data and columns:
        header = " | ".join(columns)
        sep = " | ".join(["---"] * len(columns))
        rows = "\n".join(" | ".join(str(v) for v in row) for row in data[:50])
        parts.append(f"**Results ({len(data)} rows):**\n{header}\n{sep}\n{rows}")
        if len(data) > 50:
            parts.append(f"_(showing 50 of {len(data)} rows)_")
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        cols = list(data[0].keys())
        header = " | ".join(cols)
        sep = " | ".join(["---"] * len(cols))
        rows = "\n".join(" | ".join(str(r.get(c, "")) for c in cols) for r in data[:50])
        parts.append(f"**Results ({len(data)} rows):**\n{header}\n{sep}\n{rows}")

    summary = result.get("summary") or result.get("message")
    if summary:
        parts.append(f"**Summary:** {summary}")

    raw = f"**Raw response:**\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```"
    parts.append(raw)
    return "\n\n".join(parts)


# ── Entrypoint ─────────────────────────────────────────────────────────────────
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
