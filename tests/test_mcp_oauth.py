"""Tests for MCP OAuth (src.api.mcp_oauth) and its wiring into the MCP endpoints.

JWTs are signed with a throwaway RSA key and the JWKS lookup is stubbed, so
no IdP is contacted. Covers claim validation, group → DB profile mapping, the
WWW-Authenticate / RFC 9728 discovery path, and that API tokens keep working
alongside (or are refused without) OAuth depending on mcp.auth.methods.
"""
import contextlib
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from src.api import mcp_oauth, mcp_sse

ISSUER = "https://idp.example.com/realms/corp"
AUDIENCE = "api://sqlatte-mcp"
VALID_API_TOKEN = "valid-token"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

OAUTH_SETTINGS = {
    "issuer": ISSUER,
    "audience": AUDIENCE,
    "required_scopes": ["mcp.access"],
    "resource_url": "https://sqlatte.example.com/mcp",
    "group_profiles": [
        {"group": "SQLatte-Marketing", "profile": "marketing"},
        {"group": "SQLatte-Ops", "profile": "ops"},
    ],
    "default_profile": None,
    "db_profiles": {
        "marketing": {"provider": "trino", "trino": {"catalog": "hive"}},
        "ops": {"provider": "bigquery", "bigquery": {}, "token_type": "discovery"},
    },
}


def _make_jwt(key=_KEY, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        "sub": "u-1",
        "preferred_username": "alice@example.com",
        "scp": "mcp.access openid",
        "groups": ["SQLatte-Marketing"],
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256")


class _FakeJWKClient:
    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": _KEY.public_key()})()


class _FakeConfigDB:
    def validate_api_token(self, token):
        if token != VALID_API_TOKEN:
            return None
        return {"username": "bob", "db_config": {"provider": "trino"}, "token_type": "query"}

    def list_mask_rules(self):
        return []


@pytest.fixture
def auth_config(monkeypatch):
    cfg = {"methods": ["token", "oauth"], "oauth": dict(OAUTH_SETTINGS)}
    monkeypatch.setattr(mcp_oauth, "_auth_config", lambda: cfg)
    monkeypatch.setattr(mcp_oauth, "_jwks_client", lambda settings: _FakeJWKClient())
    return cfg


# ── validate_bearer ───────────────────────────────────────────────────────────

def test_valid_token_maps_group_to_profile(auth_config):
    info = mcp_oauth.validate_bearer(_make_jwt())
    assert info == {
        "username": "alice@example.com",
        "db_config": {"provider": "trino", "trino": {"catalog": "hive"}},
        "token_type": "query",
        "profile": "marketing",
    }


def test_profile_token_type_override_is_not_leaked_into_db_config(auth_config):
    info = mcp_oauth.validate_bearer(_make_jwt(groups=None, roles=["SQLatte-Ops"]))
    assert info["profile"] == "ops"
    assert info["token_type"] == "discovery"
    assert "token_type" not in info["db_config"]
    # the configured profile itself must stay untouched
    assert auth_config["oauth"]["db_profiles"]["ops"]["token_type"] == "discovery"


@pytest.mark.parametrize("overrides", [
    {"aud": "api://someone-else"},
    {"iss": "https://evil.example.com"},
    {"exp": int(time.time()) - 3600},
    {"exp": None},
])
def test_bad_claims_rejected(auth_config, overrides):
    with pytest.raises(mcp_oauth.OAuthError) as e:
        mcp_oauth.validate_bearer(_make_jwt(**overrides))
    assert e.value.status_code == 401


def test_wrong_signature_rejected(auth_config):
    with pytest.raises(mcp_oauth.OAuthError) as e:
        mcp_oauth.validate_bearer(_make_jwt(key=_OTHER_KEY))
    assert e.value.status_code == 401


def test_missing_scope_is_403(auth_config):
    with pytest.raises(mcp_oauth.OAuthError) as e:
        mcp_oauth.validate_bearer(_make_jwt(scp="openid"))
    assert e.value.status_code == 403
    assert e.value.error == "insufficient_scope"


def test_scope_claim_string_accepted(auth_config):
    info = mcp_oauth.validate_bearer(_make_jwt(scp=None, scope="mcp.access"))
    assert info["username"] == "alice@example.com"


def test_no_matching_group_is_403(auth_config):
    with pytest.raises(mcp_oauth.OAuthError) as e:
        mcp_oauth.validate_bearer(_make_jwt(groups=["Someone-Else"]))
    assert e.value.status_code == 403


def test_default_profile_used_when_no_group_matches(auth_config):
    auth_config["oauth"]["default_profile"] = "marketing"
    info = mcp_oauth.validate_bearer(_make_jwt(groups=[]))
    assert info["profile"] == "marketing"


def test_username_claim_fallback(auth_config):
    info = mcp_oauth.validate_bearer(_make_jwt(preferred_username=None, upn="alice@corp"))
    assert info["username"] == "alice@corp"


def test_undefined_profile_is_server_error(auth_config):
    auth_config["oauth"]["group_profiles"] = [{"group": "SQLatte-Marketing", "profile": "missing"}]
    with pytest.raises(mcp_oauth.OAuthError) as e:
        mcp_oauth.validate_bearer(_make_jwt())
    assert e.value.status_code == 500


def test_metadata_url_follows_rfc9728(auth_config):
    request = type("R", (), {"base_url": "http://ignored/"})()
    assert mcp_oauth.metadata_url(request) == \
        "https://sqlatte.example.com/.well-known/oauth-protected-resource/mcp"


# ── Endpoint wiring (Streamable HTTP) ─────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, auth_config):
    monkeypatch.setattr("src.core.config_db.get_config_db", lambda: _FakeConfigDB())
    monkeypatch.setattr(mcp_sse, "_http_sessions", {})

    created = []
    real_create = mcp_sse._create_session

    def spy_create(token, token_info):
        created.append((token, token_info["username"]))
        return real_create(token, token_info)

    monkeypatch.setattr(mcp_sse, "_create_session", spy_create)

    async def fake_api(method, path, **kwargs):
        return {"tables": ["orders"]} if path == "/auth/tables" else {}

    monkeypatch.setattr(mcp_sse, "_api", fake_api)

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
        routes=[
            Route("/mcp/http", mcp_sse.mcp_http_endpoint, methods=["GET", "POST", "DELETE"]),
            Route("/.well-known/oauth-protected-resource/{path:path}",
                  mcp_oauth.handle_protected_resource_metadata, methods=["GET"]),
        ],
        lifespan=lifespan,
    )
    with TestClient(app) as c:
        c.created = created
        yield c


def _list_tables(client, headers):
    return client.post(
        "/mcp/http", headers={**HEADERS, **headers},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "list_tables", "arguments": {}}},
    )


def test_bearer_token_reaches_tools(client):
    resp = _list_tables(client, {"Authorization": f"Bearer {_make_jwt()}"})
    assert resp.status_code == 200
    assert "orders" in resp.json()["result"]["content"][0]["text"]
    # OAuth sessions carry no API token (it's only used for budget lookups)
    assert client.created == [(None, "alice@example.com")]


def test_oauth_session_reused_across_refreshed_tokens(client):
    _list_tables(client, {"Authorization": f"Bearer {_make_jwt()}"})
    _list_tables(client, {"Authorization": f"Bearer {_make_jwt(iat=int(time.time()) + 1)}"})
    assert len(client.created) == 1


def test_missing_credentials_advertises_metadata(client):
    resp = _list_tables(client, {})
    assert resp.status_code == 401
    challenge = resp.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert 'resource_metadata="https://sqlatte.example.com/.well-known/oauth-protected-resource/mcp"' in challenge
    assert 'scope="mcp.access"' in challenge


def test_invalid_bearer_is_401_with_error(client):
    resp = _list_tables(client, {"Authorization": f"Bearer {_make_jwt(key=_OTHER_KEY)}"})
    assert resp.status_code == 401
    assert 'error="invalid_token"' in resp.headers["www-authenticate"]


def test_api_token_still_works_alongside_oauth(client):
    resp = _list_tables(client, {"x-mcp-token": VALID_API_TOKEN})
    assert resp.status_code == 200
    assert client.created == [(VALID_API_TOKEN, "bob")]


def test_api_token_refused_when_oauth_only(client, auth_config):
    auth_config["methods"] = ["oauth"]
    resp = _list_tables(client, {"x-mcp-token": VALID_API_TOKEN})
    assert resp.status_code == 401


def test_bearer_ignored_when_oauth_disabled(client, auth_config):
    auth_config["methods"] = ["token"]
    resp = _list_tables(client, {"Authorization": f"Bearer {_make_jwt()}"})
    assert resp.status_code == 401
    assert "www-authenticate" not in resp.headers


def test_protected_resource_metadata(client):
    resp = client.get("/.well-known/oauth-protected-resource/mcp")
    assert resp.status_code == 200
    assert resp.json() == {
        "resource": "https://sqlatte.example.com/mcp",
        "authorization_servers": [ISSUER],
        "scopes_supported": ["mcp.access"],
        "bearer_methods_supported": ["header"],
    }


# ── Per-user DB credential binding ────────────────────────────────────────────

class _BindingDB:
    def __init__(self):
        self.rows = {}

    def set_oauth_binding(self, identity, username, credentials):
        self.rows[identity] = credentials

    def get_oauth_binding(self, identity):
        return self.rows.get(identity)

    def delete_oauth_binding(self, identity):
        return self.rows.pop(identity, None) is not None


@pytest.fixture
def binding_db(monkeypatch, auth_config):
    auth_config["oauth"]["credential_binding"] = {"enabled": True}
    db = _BindingDB()
    monkeypatch.setattr("src.core.config_db.get_config_db", lambda: db)
    monkeypatch.setattr(mcp_oauth, "_verify_db_credentials", lambda cfg: None)
    return db


@pytest.fixture
def link_client(binding_db):
    app = Starlette(routes=[Route("/mcp/oauth/link", mcp_oauth.handle_link,
                                  methods=["GET", "POST", "DELETE"])])
    with TestClient(app) as c:
        yield c


def _auth(**claims):
    return {"Authorization": f"Bearer {_make_jwt(**claims)}"}


def test_unlinked_user_gets_account_not_linked(binding_db):
    with pytest.raises(mcp_oauth.OAuthError) as e:
        mcp_oauth.validate_bearer(_make_jwt())
    assert e.value.status_code == 403
    assert e.value.error == "account_not_linked"


def test_linked_user_queries_with_own_credentials(binding_db):
    binding_db.rows[f"{ISSUER}:u-1"] = {"user": "alice", "password": "s3cret"}
    info = mcp_oauth.validate_bearer(_make_jwt())
    assert info["db_config"]["trino"] == {"catalog": "hive", "user": "alice", "password": "s3cret"}
    # the shared profile in config must not be mutated
    assert "user" not in OAUTH_SETTINGS["db_profiles"]["marketing"]["trino"]


def test_binding_is_per_identity(binding_db):
    binding_db.rows[f"{ISSUER}:u-1"] = {"user": "alice", "password": "a"}
    with pytest.raises(mcp_oauth.OAuthError):
        mcp_oauth.validate_bearer(_make_jwt(sub="u-2"))


def test_entra_identity_uses_tenant_and_oid(binding_db):
    binding_db.rows["tenant-1:oid-1"] = {"user": "alice", "password": "a"}
    info = mcp_oauth.validate_bearer(_make_jwt(tid="tenant-1", oid="oid-1", sub="app-scoped"))
    assert info["db_config"]["trino"]["user"] == "alice"


def test_binding_off_keeps_shared_profile(auth_config):
    info = mcp_oauth.validate_bearer(_make_jwt())
    assert info["db_config"]["trino"] == {"catalog": "hive"}


def test_binding_unsupported_provider_is_server_error(binding_db):
    with pytest.raises(mcp_oauth.OAuthError) as e:
        mcp_oauth.validate_bearer(_make_jwt(groups=["SQLatte-Ops"]))
    assert e.value.status_code == 500


def test_link_status_and_unlink_roundtrip(link_client, binding_db):
    assert link_client.get("/mcp/oauth/link", headers=_auth()).json() == \
        {"linked": False, "db_user": None, "profile": "marketing"}

    resp = link_client.post("/mcp/oauth/link", headers=_auth(),
                            json={"user": "alice", "password": "s3cret"})
    assert resp.status_code == 200
    assert resp.json() == {"linked": True, "db_user": "alice", "profile": "marketing"}
    assert "s3cret" not in resp.text
    assert binding_db.rows[f"{ISSUER}:u-1"] == {"user": "alice", "password": "s3cret"}

    assert link_client.get("/mcp/oauth/link", headers=_auth()).json()["db_user"] == "alice"
    assert link_client.delete("/mcp/oauth/link", headers=_auth()).json() == {"linked": False}
    assert binding_db.rows == {}


def test_link_verifies_credentials_before_saving(link_client, binding_db, monkeypatch):
    def reject(cfg):
        raise RuntimeError("401 Unauthorized for user alice at radar.internal")
    monkeypatch.setattr(mcp_oauth, "_verify_db_credentials", reject)

    resp = link_client.post("/mcp/oauth/link", headers=_auth(),
                            json={"user": "alice", "password": "wrong"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_credentials"
    assert "radar.internal" not in resp.text      # driver error is not echoed
    assert binding_db.rows == {}


def test_link_verifies_with_profile_target_and_user_credentials(link_client, monkeypatch):
    seen = []
    monkeypatch.setattr(mcp_oauth, "_verify_db_credentials", lambda cfg: seen.append(cfg))
    link_client.post("/mcp/oauth/link", headers=_auth(), json={"user": "alice", "password": "pw"})
    assert seen[0]["trino"] == {"catalog": "hive", "user": "alice", "password": "pw"}


def test_link_requires_valid_bearer(link_client):
    assert link_client.post("/mcp/oauth/link", json={"user": "a", "password": "b"}).status_code == 401
    bad = {"Authorization": f"Bearer {_make_jwt(key=_OTHER_KEY)}"}
    assert link_client.get("/mcp/oauth/link", headers=bad).status_code == 401


def test_link_rejects_incomplete_body(link_client):
    resp = link_client.post("/mcp/oauth/link", headers=_auth(), json={"user": "alice"})
    assert resp.status_code == 400


def test_link_disabled_without_binding(auth_config):
    app = Starlette(routes=[Route("/mcp/oauth/link", mcp_oauth.handle_link, methods=["GET"])])
    with TestClient(app) as c:
        assert c.get("/mcp/oauth/link", headers=_auth()).status_code == 404
