"""
LDAP authentication — optional identity check for the admin login and the
SQLatte Assistant login gate. Disabled unless `ldap.enabled: true` in config.

Two bind modes, chosen by which config keys are present:
  - Direct bind:  `user_dn_template` — DN is built directly from the username,
                   then bound with the user's own password. No service
                   account needed. Simple, works for flat directories.
  - Search+bind:  `bind_dn` / `bind_password` (a service account) search the
                   directory for the user's DN using `user_search_filter`,
                   then re-bind as that DN with the user's password. Needed
                   when users live under varying OUs (typical for AD).
"""
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Reject usernames that could break out of a DN/filter before they ever reach
# ldap3's own escaping — defense in depth, not a substitute for it.
_SAFE_USERNAME = re.compile(r'^[A-Za-z0-9._@\-]{1,256}$')


def _get_ldap_config() -> Dict[str, Any]:
    from src.core.config_manager_enhanced import config_manager
    config = config_manager.get_config()
    return config.get("ldap", {})


def is_enabled() -> bool:
    return bool(_get_ldap_config().get("enabled", False))


def authenticate(username: str, password: str) -> Optional[str]:
    """
    Bind against the configured LDAP/AD server as `username`/`password`.

    Returns the canonical username on success, None on any failure — bad
    credentials, misconfiguration, or an unreachable directory. Never raises;
    callers should fall back to another auth method or reject the login.
    """
    if not username or not password:
        return None

    if not _SAFE_USERNAME.match(username):
        logger.warning("LDAP auth rejected: username contains disallowed characters")
        return None

    cfg = _get_ldap_config()
    if not cfg.get("enabled", False):
        return None

    server_uri = cfg.get("server", "")
    if not server_uri:
        logger.error("SECURITY: ldap.enabled=true but ldap.server is not configured")
        return None

    try:
        import ldap3
    except ImportError:
        logger.error("ldap.enabled=true but the 'ldap3' package is not installed")
        return None

    # ldap3's Server/Connection pass this straight into socket setsockopt calls
    # that require a plain int — a float here raises struct.error deep inside
    # ldap3, not a catchable auth failure.
    timeout = int(cfg.get("connect_timeout", 5))

    try:
        server = ldap3.Server(
            server_uri,
            use_ssl=bool(cfg.get("use_ssl", server_uri.startswith("ldaps://"))),
            connect_timeout=timeout,
        )

        user_dn_template = cfg.get("user_dn_template")
        if user_dn_template:
            return _direct_bind(ldap3, server, user_dn_template, username, password, timeout)

        return _search_and_bind(ldap3, server, cfg, username, password, timeout)

    except Exception as e:
        logger.error("LDAP authentication error: %s", e)
        return None


def _direct_bind(ldap3, server, user_dn_template: str, username: str, password: str, timeout: float) -> Optional[str]:
    user_dn = user_dn_template.format(username=username)
    conn = ldap3.Connection(
        server, user=user_dn, password=password,
        receive_timeout=timeout, raise_exceptions=False,
    )
    try:
        if conn.bind():
            logger.info("LDAP direct bind succeeded for %s", username)
            return username
        logger.info("LDAP direct bind failed for %s", username)
        return None
    finally:
        conn.unbind()


def _search_and_bind(ldap3, server, cfg: Dict[str, Any], username: str, password: str, timeout: float) -> Optional[str]:
    bind_dn = cfg.get("bind_dn", "")
    bind_password = cfg.get("bind_password", "")
    base_dn = cfg.get("base_dn", "")
    user_search_filter = cfg.get("user_search_filter", "(uid={username})")

    if not (bind_dn and base_dn):
        logger.error("SECURITY: LDAP search+bind mode requires ldap.bind_dn and ldap.base_dn")
        return None

    search_conn = ldap3.Connection(
        server, user=bind_dn, password=bind_password,
        receive_timeout=timeout, raise_exceptions=False,
    )
    try:
        if not search_conn.bind():
            logger.error("LDAP service account bind failed — check ldap.bind_dn/bind_password")
            return None

        safe_username = ldap3.utils.conv.escape_filter_chars(username)
        search_filter = user_search_filter.format(username=safe_username)

        search_conn.search(search_base=base_dn, search_filter=search_filter, attributes=[])

        if not search_conn.entries:
            logger.info("LDAP user not found: %s", username)
            return None
        if len(search_conn.entries) > 1:
            logger.warning("LDAP search matched multiple entries for %s; refusing to authenticate", username)
            return None

        user_dn = search_conn.entries[0].entry_dn
    finally:
        search_conn.unbind()

    user_conn = ldap3.Connection(
        server, user=user_dn, password=password,
        receive_timeout=timeout, raise_exceptions=False,
    )
    try:
        if user_conn.bind():
            logger.info("LDAP search+bind succeeded for %s", username)
            return username
        logger.info("LDAP search+bind failed for %s", username)
        return None
    finally:
        user_conn.unbind()
