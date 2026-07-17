"""Tests for src.core.sql_validator — SELECT-only enforcement, the AST
security layer (sqlglot), and the regex-based fallback.

Several cases here are regression tests for bypasses found during review:
they must keep failing (i.e. the query must be rejected) even if the
implementation changes.
"""
import pytest

from src.core.sql_validator import (
    _parse_statements,
    dialect_for_provider,
    is_select_only,
    risk_score,
    validate_identifier,
    validate_job_id,
    violation_reason,
)


class TestDialectForProvider:
    def test_known_providers_map_to_sqlglot_dialects(self):
        assert dialect_for_provider("trino") == "trino"
        assert dialect_for_provider("postgresql") == "postgres"
        assert dialect_for_provider("mysql") == "mysql"
        assert dialect_for_provider("bigquery") == "bigquery"

    def test_case_insensitive(self):
        assert dialect_for_provider("BigQuery") == "bigquery"

    @pytest.mark.parametrize("provider", ["oracle", "", None])
    def test_unknown_or_empty_provider_returns_none(self, provider):
        assert dialect_for_provider(provider) is None


class TestValidateIdentifier:
    def test_allows_simple_and_qualified_names(self):
        assert validate_identifier("orders") == "orders"
        assert validate_identifier("catalog.schema.table") == "catalog.schema.table"

    @pytest.mark.parametrize(
        "bad", ["orders; DROP TABLE x", "orders--", "a b", "'; DROP--", ""]
    )
    def test_rejects_anything_outside_the_safe_charset(self, bad):
        with pytest.raises(ValueError):
            validate_identifier(bad)


class TestValidateJobId:
    def test_allows_bigquery_job_id_format(self):
        job_id = "my-project:US.bquxjob_1234"
        assert validate_job_id(job_id) == job_id

    @pytest.mark.parametrize("bad", ["job id", "job;DROP", ""])
    def test_rejects_invalid_job_id(self, bad):
        with pytest.raises(ValueError):
            validate_job_id(bad)


SAFE_QUERIES = [
    "SELECT * FROM users",
    "SELECT id, name FROM users LIMIT 10",
    "SELECT insert_date FROM t",  # column name containing a blacklisted keyword substring
    "SELECT * FROM a CROSS JOIN b",
    "WITH cte AS (SELECT 1) SELECT * FROM cte",
    "SELECT 1 UNION SELECT 2",
    "SELECT * FROM t WHERE x IN (SELECT y FROM z)",
]

UNSAFE_QUERIES = [
    "DROP TABLE users",
    "INSERT INTO t VALUES (1)",
    "SELECT 1; DROP TABLE users",
    "SELECT 1; SELECT 2",  # multiple statements rejected even if each is individually safe
    "SELECT pg_sleep(5)",
    "SELECT dblink_exec('conn', 'DROP TABLE x')",
    'SELECT "pg_sleep"(5)',
    "WITH deleted AS (DELETE FROM users WHERE id=1 RETURNING *) SELECT * FROM deleted",
    "WITH ins AS (INSERT INTO users(name) VALUES ('x') RETURNING *) SELECT * FROM ins",
    "WITH upd AS (UPDATE users SET name='x' RETURNING *) SELECT * FROM upd",
]


class TestIsSelectOnly:
    @pytest.mark.parametrize("sql", SAFE_QUERIES)
    def test_allows_safe_queries(self, sql):
        assert is_select_only(sql, dialect="postgres") is True

    @pytest.mark.parametrize("sql", UNSAFE_QUERIES)
    def test_rejects_unsafe_queries(self, sql):
        assert is_select_only(sql, dialect="postgres") is False

    def test_writable_cte_delete_is_blocked(self):
        # A PostgreSQL writable CTE lets a DELETE masquerade as a top-level
        # SELECT. Checking only the root node's type missed this; the AST
        # layer must walk the whole tree for nested mutations.
        sql = "WITH deleted AS (DELETE FROM users WHERE id=1 RETURNING *) SELECT * FROM deleted"
        assert is_select_only(sql, dialect="postgres") is False
        assert "DELETE" in violation_reason(sql, dialect="postgres")

    def test_quoted_identifier_does_not_bypass_dangerous_function_check(self):
        # Double-quoting a function name used to let it slip past the old
        # regex-only check: the quote-stripping step blanked the identifier
        # out before the dangerous-function scan ever ran.
        assert is_select_only('SELECT "pg_sleep"(5)', dialect="postgres") is False

    def test_schema_qualified_dangerous_function_is_still_caught(self):
        assert is_select_only("SELECT pg_catalog.pg_sleep(5)", dialect="postgres") is False

    def test_falls_back_to_regex_when_sqlglot_cannot_parse(self):
        garbage = "SELECT ((( invalid ]]] DROP"
        assert _parse_statements(garbage, "postgres") is None  # confirms the fallback path is exercised
        assert is_select_only(garbage, dialect="postgres") is False

    def test_bigquery_backtick_identifiers_parse_with_correct_dialect(self):
        sql = "SELECT * FROM `my-project.dataset.table` LIMIT 10"
        assert is_select_only(sql, dialect="bigquery") is True


class TestViolationReason:
    def test_non_select_reports_statement_type(self):
        assert "DROP" in violation_reason("DROP TABLE users", dialect="postgres").upper()

    def test_dangerous_function_named_in_reason(self):
        assert "pg_sleep" in violation_reason("SELECT pg_sleep(5)", dialect="postgres")

    def test_multiple_statements_reports_that_reason(self):
        reason = violation_reason("SELECT 1; SELECT 2", dialect="postgres")
        assert "Multiple" in reason


class TestRiskScore:
    def test_safe_bounded_query_scores_zero(self):
        assert risk_score("SELECT id FROM t LIMIT 5", dialect="postgres") == 0

    def test_select_star_and_missing_limit_increase_score(self):
        assert risk_score("SELECT * FROM t", dialect="postgres") > 0

    def test_cross_join_scores_higher_than_plain_query(self):
        bare = risk_score("SELECT * FROM t", dialect="postgres")
        joined = risk_score("SELECT * FROM a CROSS JOIN b", dialect="postgres")
        assert joined > bare

    def test_dangerous_function_scores_high(self):
        assert risk_score("SELECT pg_sleep(5)", dialect="postgres") >= 40

    def test_non_select_statement_scores_high(self):
        assert risk_score("DROP TABLE users", dialect="postgres") >= 70

    def test_score_stays_within_0_to_100(self):
        sql = "SELECT pg_sleep(5), dblink_exec('a','b'), xp_cmdshell('c')"
        assert 0 <= risk_score(sql, dialect="postgres") <= 100
