"""Tests for the MCP Streamable HTTP endpoint (src.api.mcp_sse.mcp_http_endpoint).

Drives the endpoint over real HTTP + MCP JSON-RPC, with the token DB and the
internal SQLatte API (_api) stubbed out. The important properties:

  - token auth happens per request (missing/invalid → 401, never reaches MCP)
  - the per-request contextvars set by the endpoint reach the tool handlers,
    which run in a task spawned by the session manager
  - one auth session is reused per token instead of one per tool call
"""
import contextlib

import pytest
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from src.api import mcp_sse
from src.plugins.session_manager import auth_session_manager

VALID_TOKEN = "valid-token"

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


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
def client(monkeypatch):
    monkeypatch.setattr("src.core.config_db.get_config_db", lambda: _FakeConfigDB())
    monkeypatch.setattr(mcp_sse, "_http_sessions", {})

    api_calls = []

    async def fake_api(method, path, **kwargs):
        api_calls.append((method, path, mcp_sse._ctx_session_id.get()))
        if path == "/auth/tables":
            return {"tables": ["orders", "customers"]}
        return {}

    monkeypatch.setattr(mcp_sse, "_api", fake_api)

    # run() can only be entered once per manager, so each test gets its own.
    manager = StreamableHTTPSessionManager(
        app=mcp_sse.server, json_response=True, stateless=True,
        security_settings=mcp_sse._security,
    )
    monkeypatch.setattr(mcp_sse, "mcp_http_manager", manager)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    app = Starlette(
        routes=[Route("/mcp/http", mcp_sse.mcp_http_endpoint, methods=["GET", "POST", "DELETE"])],
        lifespan=lifespan,
    )
    with TestClient(app) as c:
        c.api_calls = api_calls
        yield c


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def test_missing_token_returns_401(client):
    resp = client.post("/mcp/http", headers=HEADERS, json=_rpc("tools/list"))
    assert resp.status_code == 401


def test_invalid_token_returns_401(client):
    resp = client.post(
        "/mcp/http", headers={**HEADERS, "x-mcp-token": "nope"}, json=_rpc("tools/list"),
    )
    assert resp.status_code == 401


def test_initialize(client):
    resp = client.post(
        "/mcp/http",
        headers={**HEADERS, "x-mcp-token": VALID_TOKEN},
        json=_rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        }),
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["serverInfo"]["name"] == "sqlatte"


def test_tool_call_sees_request_session(client):
    resp = client.post(
        "/mcp/http",
        headers={**HEADERS, "x-mcp-token": VALID_TOKEN},
        json=_rpc("tools/call", {"name": "list_tables", "arguments": {}}),
    )
    assert resp.status_code == 200
    text = resp.json()["result"]["content"][0]["text"]
    assert "orders" in text and "customers" in text

    # The tool handler ran in the manager's task and still saw the
    # session_id the endpoint set for this request. The SDK also runs
    # list_tools (→ /auth/config) on the first call to validate arguments,
    # so check every internal call carried the same session.
    tables_calls = [c for c in client.api_calls if c[1] == "/auth/tables"]
    assert len(tables_calls) == 1
    session_id = tables_calls[0][2]
    assert {c[2] for c in client.api_calls} == {session_id}
    assert auth_session_manager.get_session(session_id).username == "alice"


def test_token_query_param_is_accepted(client):
    resp = client.post(
        f"/mcp/http?token={VALID_TOKEN}",
        headers=HEADERS,
        json=_rpc("tools/call", {"name": "list_tables", "arguments": {}}),
    )
    assert resp.status_code == 200


def test_session_is_reused_per_token(client):
    for i in range(3):
        resp = client.post(
            "/mcp/http",
            headers={**HEADERS, "x-mcp-token": VALID_TOKEN},
            json=_rpc("tools/call", {"name": "list_tables", "arguments": {}}, id_=i),
        )
        assert resp.status_code == 200

    session_ids = {call[2] for call in client.api_calls}
    assert len(session_ids) == 1


def test_expired_session_is_recreated(client):
    headers = {**HEADERS, "x-mcp-token": VALID_TOKEN}
    body = _rpc("tools/call", {"name": "list_tables", "arguments": {}})

    client.post("/mcp/http", headers=headers, json=body)
    first_session = client.api_calls[-1][2]
    auth_session_manager.sessions.pop(first_session)

    client.post("/mcp/http", headers=headers, json=body)
    second_session = client.api_calls[-1][2]
    assert second_session != first_session
