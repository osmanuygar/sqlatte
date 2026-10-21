"""Tests for PostgreSQLProvider.execute_query — specifically the watchdog
query-timeout added alongside TrinoProvider's (see test_trino_provider.py's
sibling gap: that one has no timeout tests either). Mocks the connection
layer (no live Postgres needed); the timeout tests use a real short sleep
inside the mocked cursor so the real threading.Timer watchdog has genuine
wall-clock time to fire — self.timeout is set to a few tens of ms to keep
the suite fast.
"""
import time
from unittest.mock import MagicMock

from src.providers.database.postgresql_provider import PostgreSQLProvider


def _provider_with_fake_conn(timeout=300):
    """A PostgreSQLProvider whose .connect() returns a MagicMock
    connection/cursor pair, with `timeout` pre-set (skips config parsing)."""
    provider = PostgreSQLProvider({"host": "h", "database": "d", "user": "u", "password": "p"})
    provider.timeout = timeout
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    provider.connect = MagicMock(return_value=conn)
    return provider, conn, cursor


class TestExecuteQueryHappyPath:
    def test_returns_columns_and_rows(self):
        provider, conn, cursor = _provider_with_fake_conn()
        cursor.description = [("id",), ("name",)]
        cursor.fetchall.return_value = [(1, "a"), (2, "b")]

        columns, data = provider.execute_query("SELECT * FROM t")

        assert columns == ["id", "name"]
        assert data == [[1, "a"], [2, "b"]]

    def test_non_select_with_no_description_returns_empty(self):
        provider, conn, cursor = _provider_with_fake_conn()
        cursor.description = None

        columns, data = provider.execute_query("INSERT INTO t VALUES (1)")

        assert (columns, data) == ([], [])

    def test_cursor_and_connection_are_closed(self):
        provider, conn, cursor = _provider_with_fake_conn()
        cursor.description = [("id",)]
        cursor.fetchall.return_value = [(1,)]

        provider.execute_query("SELECT 1")

        cursor.close.assert_called_once()
        conn.close.assert_called_once()

    def test_fast_query_never_calls_cancel(self):
        provider, conn, cursor = _provider_with_fake_conn(timeout=5)
        cursor.description = [("id",)]
        cursor.fetchall.return_value = [(1,)]

        provider.execute_query("SELECT 1")

        conn.cancel.assert_not_called()

    def test_db_error_is_wrapped_with_context(self):
        provider, conn, cursor = _provider_with_fake_conn()
        cursor.execute.side_effect = Exception("syntax error at or near")

        try:
            provider.execute_query("SELECT bad sql")
            assert False, "expected an exception"
        except Exception as e:
            assert "Query execution failed" in str(e)


class TestExecuteQueryDefaultTimeout:
    def test_default_timeout_is_300s_when_not_configured(self):
        provider = PostgreSQLProvider({"host": "h", "database": "d", "user": "u", "password": "p"})
        assert provider.timeout == 300

    def test_configured_timeout_overrides_default(self):
        provider = PostgreSQLProvider({"host": "h", "database": "d", "user": "u", "password": "p", "timeout": 42})
        assert provider.timeout == 42


class TestExecuteQueryWatchdogTimeout:
    """timeout is set to a few tens of ms and the mocked cursor.execute()
    genuinely sleeps past it, so the real threading.Timer watchdog fires
    during that sleep — same mechanism as production, just compressed to
    keep the test fast."""

    def test_slow_query_is_cancelled_and_raises_timeout_error(self):
        provider, conn, cursor = _provider_with_fake_conn(timeout=0.05)

        def _slow_execute(sql):
            time.sleep(0.2)  # long enough for the 0.05s watchdog to fire first
            cursor.description = [("id",)]

        cursor.execute.side_effect = _slow_execute
        cursor.fetchall.return_value = [(1,)]

        try:
            provider.execute_query("SELECT pg_sleep(10)")
            assert False, "expected TimeoutError"
        except TimeoutError as e:
            assert "0.05" in str(e)

        conn.cancel.assert_called_once()

    def test_watchdog_cancel_failure_is_swallowed(self):
        # conn.cancel() itself raising must not crash the watchdog thread or
        # surface as anything other than the TimeoutError to the caller.
        provider, conn, cursor = _provider_with_fake_conn(timeout=0.05)
        conn.cancel.side_effect = Exception("connection already closed")

        def _slow_execute(sql):
            time.sleep(0.2)
            cursor.description = [("id",)]

        cursor.execute.side_effect = _slow_execute
        cursor.fetchall.return_value = [(1,)]

        try:
            provider.execute_query("SELECT pg_sleep(10)")
            assert False, "expected TimeoutError"
        except TimeoutError:
            pass

    def test_timer_is_cancelled_on_fast_completion_no_stray_cancel_call(self):
        # A fast query finishing well inside the window must never trigger
        # conn.cancel() — the Timer.cancel() in `finally` must actually
        # defuse it (checked by waiting past the window afterwards).
        provider, conn, cursor = _provider_with_fake_conn(timeout=0.05)
        cursor.description = [("id",)]
        cursor.fetchall.return_value = [(1,)]

        provider.execute_query("SELECT 1")
        time.sleep(0.15)  # past the timeout window — watchdog must be dead by now

        conn.cancel.assert_not_called()

    def test_zero_timeout_disables_the_watchdog_entirely(self):
        provider, conn, cursor = _provider_with_fake_conn(timeout=0)

        def _slow_execute(sql):
            time.sleep(0.1)
            cursor.description = [("id",)]

        cursor.execute.side_effect = _slow_execute
        cursor.fetchall.return_value = [(1,)]

        columns, data = provider.execute_query("SELECT 1")

        assert (columns, data) == (["id"], [[1]])
        conn.cancel.assert_not_called()
