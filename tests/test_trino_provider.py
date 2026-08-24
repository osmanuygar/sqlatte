"""Tests for TrinoProvider.discover_tables — the SQL/filter logic backing
both /auth/discover and the catalog-less /auth/tables fallback. Mocks the
connection layer (no live Trino needed) to check what SQL gets built and
that the allowed_catalogs schema-level filter is applied correctly.
"""
from unittest.mock import MagicMock

from src.providers.database.trino_provider import TrinoProvider


def _provider_with_fake_cursor(rows):
    """A TrinoProvider whose .connect() returns a MagicMock connection/cursor
    recording the executed SQL, with cursor.fetchall() returning `rows`."""
    provider = TrinoProvider({"host": "h", "port": 8080, "user": "u", "password": "p"})
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value = cursor
    provider.connect = MagicMock(return_value=conn)
    return provider, cursor


class TestDiscoverTablesQueryBuilding:
    def test_empty_search_term_uses_match_all_pattern_no_catalog_filter(self):
        provider, cursor = _provider_with_fake_cursor([])
        provider.discover_tables("")
        sql, params = cursor.execute.call_args[0]
        assert params[0] == "%"
        assert "table_cat IN" not in sql

    def test_search_term_is_wrapped_in_wildcards_and_lowercased(self):
        provider, cursor = _provider_with_fake_cursor([])
        provider.discover_tables("CampaigN")
        _, params = cursor.execute.call_args[0]
        assert params[0] == "%campaign%"

    def test_catalog_schema_map_adds_catalog_in_filter(self):
        provider, cursor = _provider_with_fake_cursor([])
        provider.discover_tables("", {"s3_edr_accesslog": ["edr"], "s3_geoip": ["cloudflare"]})
        sql, params = cursor.execute.call_args[0]
        assert "table_cat IN (?, ?)" in sql
        assert set(params[1:]) == {"s3_edr_accesslog", "s3_geoip"}

    def test_no_catalog_schema_map_means_unrestricted(self):
        provider, cursor = _provider_with_fake_cursor([])
        provider.discover_tables("campaign", None)
        sql, params = cursor.execute.call_args[0]
        assert "table_cat IN" not in sql
        assert len(params) == 1


class TestDiscoverTablesResultFiltering:
    def test_row_in_allowed_catalog_and_schema_is_kept(self):
        rows = [("s3_edr_accesslog", "edr", "access_log")]
        provider, cursor = _provider_with_fake_cursor(rows)
        result = provider.discover_tables("", {"s3_edr_accesslog": ["edr"]})
        assert result["matches"] == [{"catalog": "s3_edr_accesslog", "schema": "edr", "table": "access_log"}]

    def test_row_in_disallowed_schema_for_an_allowed_catalog_is_dropped(self):
        # Simulates the DB (or a case mismatch) handing back a schema the
        # allowlist doesn't cover for that catalog — table_cat IN (...) only
        # narrows by catalog, so this half of the filter must happen in
        # Python, per-row, using the catalog's specific allowed schema list.
        rows = [
            ("s3_edr_accesslog", "edr", "access_log"),
            ("s3_edr_accesslog", "some_other_schema", "leaked_table"),
        ]
        provider, cursor = _provider_with_fake_cursor(rows)
        result = provider.discover_tables("", {"s3_edr_accesslog": ["edr"]})
        tables = [m["table"] for m in result["matches"]]
        assert tables == ["access_log"]

    def test_empty_schema_list_for_a_catalog_allows_any_schema(self):
        rows = [
            ("mongo_stores_db", "stores", "orders"),
            ("mongo_stores_db", "anything_else", "t"),
        ]
        provider, cursor = _provider_with_fake_cursor(rows)
        result = provider.discover_tables("", {"mongo_stores_db": []})
        tables = sorted(m["table"] for m in result["matches"])
        assert tables == ["orders", "t"]

    def test_no_catalog_schema_map_keeps_every_row(self):
        rows = [("any_catalog", "any_schema", "t")]
        provider, cursor = _provider_with_fake_cursor(rows)
        result = provider.discover_tables("t", None)
        assert len(result["matches"]) == 1


class TestDiscoverTablesAutoDescribe:
    def test_default_describe_limit_is_25_not_5(self):
        assert TrinoProvider.DEFAULT_DESCRIBE_LIMIT == 25

    def test_describes_up_to_default_limit_not_just_five(self):
        rows = [("cat", "sch", f"t{i}") for i in range(10)]
        provider, cursor = _provider_with_fake_cursor(rows)
        # cursor.fetchall() is reused for every DESCRIBE call too (same mock
        # cursor) — only checking how many distinct table refs get described.
        result = provider.discover_tables("")
        assert len(result["columns"]) == 10  # all 10, well past the old cap of 5

    def test_describe_limit_param_caps_the_batch(self):
        rows = [("cat", "sch", f"t{i}") for i in range(10)]
        provider, cursor = _provider_with_fake_cursor(rows)
        result = provider.discover_tables("", describe_limit=3)
        assert len(result["columns"]) == 3

    def test_reuses_one_connection_for_the_whole_describe_batch(self):
        rows = [("cat", "sch", f"t{i}") for i in range(10)]
        provider, cursor = _provider_with_fake_cursor(rows)
        provider.discover_tables("")
        # 1 connect() for the main search query + 1 for the whole describe
        # batch — not one per described table (would be 11 for 10 rows).
        assert provider.connect.call_count == 2

    def test_no_matches_skips_the_describe_connection_entirely(self):
        provider, cursor = _provider_with_fake_cursor([])
        provider.discover_tables("nonexistent")
        assert provider.connect.call_count == 1  # just the search query
