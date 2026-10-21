"""Tests for the MCP SSE endpoint (src.api.mcp_sse.mcp_app, mounted at /mcp).

The SSE stream never ends, so Starlette's TestClient can't drive a full
session. The end-to-end tests instead run the app under a real uvicorn server
in a background thread and connect with the MCP SDK's own SSE client. The
token DB and the internal SQLatte API (_api) are stubbed out.

The rejection tests don't need a stream, since auth fails before it opens.
"""
import socket
import threading
import time

import anyio
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.sse import sse_client
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from src.api import mcp_sse
from src.plugins.session_manager import auth_session_manager

VALID_TOKEN = "valid-token"


class _FakeConfigDB:
    def validate_api_token(self, token):
        if token != VALID_TOKEN:
            return None
        return {
            "username": "alice",
            "db_config": {"provider": "trino"},
            "token_type": "query",
        }

    def list_mask_rules(self):
        return []


@pytest.fixture
def api_calls(monkeypatch):
    monkeypatch.setattr("src.core.config_db.get_config_db", lambda: _FakeConfigDB())

    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, mcp_sse._ctx_session_id.get()))
        if path == "/auth/tables":
            return {"tables": ["orders", "customers"]}
        return {}

    monkeypatch.setattr(mcp_sse, "_api", fake_api)
    return calls


@pytest.fixture
def app():
    return Starlette(routes=[Mount("/mcp", app=mcp_sse.mcp_app)])


@pytest.fixture
def server_url(app, api_calls):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning",
        timeout_graceful_shutdown=1,
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


def _run_session(url, headers, fn):
    """Open an MCP SSE session, run fn(session) and return its result."""
    async def main():
        async with sse_client(url, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    return anyio.run(main)


def test_missing_token_returns_401(app, api_calls):
    resp = TestClient(app).get("/mcp/sse")
    assert resp.status_code == 401


def test_invalid_token_returns_401(app, api_calls):
    resp = TestClient(app).get("/mcp/sse", headers={"x-mcp-token": "nope"})
    assert resp.status_code == 401


def test_list_tools(server_url):
    async def fn(session):
        return await session.list_tools()

    result = _run_session(f"{server_url}/mcp/sse", {"x-mcp-token": VALID_TOKEN}, fn)
    names = {t.name for t in result.tools}
    assert {"ask_database", "list_tables", "get_schema"} <= names


def test_tool_call_sees_connection_session(server_url, api_calls):
    async def fn(session):
        return await session.call_tool("list_tables", {})

    result = _run_session(f"{server_url}/mcp/sse", {"x-mcp-token": VALID_TOKEN}, fn)
    text = result.content[0].text
    assert "orders" in text and "customers" in text

    # Every internal call (list_tools validation + the tool itself) carried
    # the session handle_sse created for this connection.
    tables_calls = [c for c in api_calls if c[1] == "/auth/tables"]
    assert len(tables_calls) == 1
    session_id = tables_calls[0][2]
    assert {c[2] for c in api_calls} == {session_id}
    assert auth_session_manager.get_session(session_id).username == "alice"


def test_token_query_param_is_accepted(server_url, api_calls):
    async def fn(session):
        return await session.call_tool("list_tables", {})

    result = _run_session(f"{server_url}/mcp/sse?token={VALID_TOKEN}", None, fn)
    assert "orders" in result.content[0].text


def test_each_connection_gets_its_own_session(server_url, api_calls):
    async def fn(session):
        return await session.call_tool("list_tables", {})

    for _ in range(2):
        _run_session(f"{server_url}/mcp/sse", {"x-mcp-token": VALID_TOKEN}, fn)

    session_ids = {c[2] for c in api_calls if c[1] == "/auth/tables"}
    assert len(session_ids) == 2
