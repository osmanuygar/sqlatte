"""
SQLatte MCP OAuth — Bearer JWT validation for the network MCP endpoints.

SQLatte acts as an OAuth 2.0 *resource server* only: an external IdP
(Entra ID, Keycloak, any OIDC provider) issues the access token, and this
module validates it against the IdP's JWKS (signature, iss, aud, exp, nbf,
scopes). The authenticated user is then mapped to a configured DB profile
via their groups/roles claim, since a JWT — unlike an SQLatte API token —
carries no db_config of its own.

Enabled via config:

    mcp:
      auth:
        methods: [token, oauth]    # default [token] — OAuth off
        oauth:
          issuer: ...
          audience: ...
          db_profiles: {...}
          group_profiles: [...]

Also serves the RFC 9728 protected-resource metadata, which MCP clients
use (via the WWW-Authenticate header on a 401) to discover the IdP.
"""
import json
import logging
import threading
import time
import urllib.request
from copy import deepcopy
from urllib.parse import urlsplit

import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_DEFAULT_USERNAME_CLAIMS = ["preferred_username", "upn", "email", "sub"]
_DEFAULT_GROUPS_CLAIMS = ["groups", "roles"]
_METADATA_PATH = "/.well-known/oauth-protected-resource"
_DISCOVERY_TTL_SECONDS = 3600


class OAuthError(Exception):
    def __init__(self, status_code: int, message: str, error: str = "invalid_token"):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error = error


# ── Config ────────────────────────────────────────────────────────────────────

def _auth_config() -> dict:
    try:
        from src.core.config_manager_enhanced import config_manager
        return config_manager.get_config().get("mcp", {}).get("auth", {}) or {}
    except Exception:
        return {}


def auth_methods() -> list[str]:
    """Enabled MCP auth methods. Defaults to API tokens only."""
    return _auth_config().get("methods") or ["token"]


def oauth_settings() -> dict:
    return _auth_config().get("oauth", {}) or {}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


# ── JWKS ──────────────────────────────────────────────────────────────────────

# jwks_url → PyJWKClient (it caches the key set itself); issuer → (jwks_uri, fetched_at)
_jwks_clients: dict[str, jwt.PyJWKClient] = {}
_discovered_jwks: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def _discover_jwks_url(issuer: str) -> str:
    cached = _discovered_jwks.get(issuer)
    if cached and time.time() - cached[1] < _DISCOVERY_TTL_SECONDS:
        return cached[0]
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with urllib.request.urlopen(url, timeout=10) as resp:
        jwks_uri = json.load(resp)["jwks_uri"]
    _discovered_jwks[issuer] = (jwks_uri, time.time())
    return jwks_uri


def _jwks_client(settings: dict) -> jwt.PyJWKClient:
    jwks_url = settings.get("jwks_url") or _discover_jwks_url(settings["issuer"])
    with _lock:
        client = _jwks_clients.get(jwks_url)
        if client is None:
            client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
            _jwks_clients[jwks_url] = client
    return client


# ── Token validation ──────────────────────────────────────────────────────────

def _token_scopes(claims: dict) -> set[str]:
    # Entra puts delegated scopes in "scp", most OIDC providers in "scope";
    # both are space-separated strings.
    scopes = set()
    for claim in ("scp", "scope"):
        value = claims.get(claim)
        if isinstance(value, str):
            scopes.update(value.split())
        elif isinstance(value, list):
            scopes.update(value)
    return scopes


def _first_claim(claims: dict, names: list[str]):
    for name in names:
        if claims.get(name):
            return claims[name]
    return None


def _user_groups(claims: dict, names: list[str]) -> set[str]:
    groups = set()
    for name in names:
        groups.update(str(g) for g in _as_list(claims.get(name)))
    return groups


def _resolve_profile(settings: dict, groups: set[str]) -> str | None:
    for mapping in settings.get("group_profiles") or []:
        if str(mapping.get("group")) in groups:
            return mapping.get("profile")
    return settings.get("default_profile")


def decode_token(token: str, settings: dict) -> dict:
    """Verify signature + standard claims. Raises OAuthError(401)."""
    if not settings.get("issuer") or not settings.get("audience"):
        logger.error("MCP OAuth enabled but mcp.auth.oauth.issuer/audience is not configured")
        raise OAuthError(500, "Authentication error", error="server_error")
    try:
        signing_key = _jwks_client(settings).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=_as_list(settings.get("algorithms")) or ["RS256"],
            audience=_as_list(settings["audience"]),
            issuer=settings["issuer"],
            leeway=settings.get("leeway_seconds", 60),
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        raise OAuthError(401, "Access token expired")
    except (jwt.PyJWKClientError, jwt.InvalidTokenError) as e:
        logger.info(f"MCP OAuth token rejected: {e}")
        raise OAuthError(401, "Invalid access token")
    except Exception as e:
        logger.error(f"MCP OAuth validation error: {e}")
        raise OAuthError(500, "Authentication error", error="server_error")


def validate_bearer(token: str) -> dict:
    """Validate an OAuth access token and map it to a DB profile.

    Returns the same shape as ConfigDB.validate_api_token() plus "profile":
      {"username": …, "db_config": …, "token_type": …, "profile": …}
    Raises OAuthError.
    """
    settings = oauth_settings()
    claims = decode_token(token, settings)

    missing = set(_as_list(settings.get("required_scopes"))) - _token_scopes(claims)
    if missing:
        raise OAuthError(403, f"Missing required scope(s): {' '.join(sorted(missing))}",
                         error="insufficient_scope")

    username = _first_claim(claims, _as_list(settings.get("username_claim")) or _DEFAULT_USERNAME_CLAIMS)
    if not username:
        raise OAuthError(401, "Access token has no username claim")

    groups = _user_groups(claims, _as_list(settings.get("groups_claim")) or _DEFAULT_GROUPS_CLAIMS)
    profile_name = _resolve_profile(settings, groups)
    if not profile_name:
        logger.info(f"MCP OAuth: no DB profile for user={username} groups={sorted(groups)}")
        raise OAuthError(403, "No SQLatte database profile is assigned to this user",
                         error="insufficient_scope")

    profile = (settings.get("db_profiles") or {}).get(profile_name)
    if not profile:
        logger.error(f"MCP OAuth: profile '{profile_name}' is not defined in mcp.auth.oauth.db_profiles")
        raise OAuthError(500, "Authentication error", error="server_error")

    db_config = deepcopy(profile)
    token_type = db_config.pop("token_type", None) or settings.get("token_type", "query")
    return {
        "username": str(username),
        "db_config": db_config,
        "token_type": token_type,
        "profile": profile_name,
    }


# ── RFC 9728 protected-resource metadata ─────────────────────────────────────

def _resource_url(request: Request) -> str:
    return oauth_settings().get("resource_url") or str(request.base_url).rstrip("/") + "/mcp"


def metadata_url(request: Request) -> str:
    """RFC 9728 §3.1: the well-known segment goes between host and path."""
    parts = urlsplit(_resource_url(request))
    return f"{parts.scheme}://{parts.netloc}{_METADATA_PATH}{parts.path.rstrip('/')}"


def www_authenticate(request: Request, error: str | None = None) -> str:
    value = f'Bearer resource_metadata="{metadata_url(request)}"'
    scopes = _as_list(oauth_settings().get("required_scopes"))
    if scopes:
        value += f', scope="{" ".join(scopes)}"'
    if error:
        value += f', error="{error}"'
    return value


async def handle_protected_resource_metadata(request: Request) -> JSONResponse:
    settings = oauth_settings()
    return JSONResponse({
        "resource": _resource_url(request),
        "authorization_servers": _as_list(settings.get("authorization_servers")) or _as_list(settings.get("issuer")),
        "scopes_supported": _as_list(settings.get("required_scopes")),
        "bearer_methods_supported": ["header"],
    })
