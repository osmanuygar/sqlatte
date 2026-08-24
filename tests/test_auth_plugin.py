"""Tests for src.plugins.auth_plugin's catalog-less token unification.

AuthPlugin._config_catalog is the single source of truth that decides
whether a session/token gets the old single-catalog lock (catalog_violation)
or the new allowlist behavior (catalog_allowlist_violation /
qualified_table_allowlist_violation) — driven by what's actually in the
session's db_config, not by the stored token_type. That's what makes old
tokens keep working unmodified: a pre-existing 'query' token's db_config
still carries a fixed catalog, so _config_catalog still returns it and the
old code path still runs, exactly as before.
"""
from src.plugins.auth_plugin import AuthPlugin


class TestConfigCatalog:
    def test_legacy_query_token_trino_config_returns_its_catalog(self):
        # Shape of db_config stored for every pre-existing 'query' token —
        # untouched by this change, must keep resolving to its fixed catalog.
        db_config = {
            "provider": "trino",
            "trino": {
                "host": "trino.internal", "port": 8443,
                "user": "alice", "password": "x",
                "catalog": "s3_edr_accesslog", "schema": "edr",
                "http_scheme": "https",
            },
        }
        assert AuthPlugin._config_catalog(db_config) == "s3_edr_accesslog"

    def test_legacy_discovery_token_trino_config_returns_none(self):
        # Shape stored for a pre-existing 'discovery' token — no catalog/schema.
        db_config = {
            "provider": "trino",
            "trino": {"host": "trino.internal", "port": 8443, "user": "alice", "password": "x", "http_scheme": "https"},
        }
        assert AuthPlugin._config_catalog(db_config) is None

    def test_new_catalog_less_login_returns_none(self):
        # Same shape as the legacy discovery token — the unified token
        # screen produces exactly this, which is the point: no new code
        # path needed, it falls into the same "catalog-less" branch.
        db_config = {
            "provider": "trino",
            "trino": {"host": "trino.internal", "port": 8443, "user": "bob", "password": "y", "http_scheme": "https"},
        }
        assert AuthPlugin._config_catalog(db_config) is None

    def test_bigquery_uses_project_id(self):
        db_config = {"provider": "bigquery", "bigquery": {"project_id": "my-gcp-project"}}
        assert AuthPlugin._config_catalog(db_config) == "my-gcp-project"

    def test_postgresql_uses_database(self):
        db_config = {"provider": "postgresql", "postgresql": {"database": "orders_db"}}
        assert AuthPlugin._config_catalog(db_config) == "orders_db"

    def test_mysql_uses_database(self):
        db_config = {"provider": "mysql", "mysql": {"database": "shop"}}
        assert AuthPlugin._config_catalog(db_config) == "shop"

    def test_missing_provider_sub_config_returns_none(self):
        assert AuthPlugin._config_catalog({"provider": "trino"}) is None

    def test_empty_db_config_returns_none(self):
        assert AuthPlugin._config_catalog({}) is None
