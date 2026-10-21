"""Tests for MySQLProvider.execute_query — the watchdog query-timeout added
alongside TrinoProvider's/PostgreSQLProvider's (see test_postgresql_provider.py
for the shared rationale). Mocks the connection layer (no live MySQL needed).

MySQL has no client-side cancel like psycopg2's conn.cancel(), so the
watchdog opens a second connection via mysql.connector.connect(...) (a
module-level call, not provider.connect()) and runs `KILL QUERY
<connection_id>` — that module-level call is what gets patched here.
"""
import time
from unittest.mock import MagicMock, patch

from src.providers.database.mysql_provider import MySQLProvider


def _provider_with_fake_conn(timeout=300, connection_id=123):
    """A MySQLProvider whose .connect() returns a MagicMock connection/cursor
    pair, with `timeout` pre-set (skips config parsing)."""
    provider = MySQLProvider({"host": "h", "database": "d", "user": "u", "password": "p"})
    provider.timeout = timeout
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.connection_id = connection_id
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

    def test_cursor_and_connection_are_closed(self):
        provider, conn, cursor = _provider_with_fake_conn()
        cursor.description = [("id",)]
        cursor.fetchall.return_value = [(1,)]

        provider.execute_query("SELECT 1")

        cursor.close.assert_called_once()
        conn.close.assert_called_once()

    def test_fast_query_never_opens_a_killer_connection(self):
        provider, conn, cursor = _provider_with_fake_conn(timeout=5)
        cursor.description = [("id",)]
        cursor.fetchall.return_value = [(1,)]

        with patch("src.providers.database.mysql_provider.mysql.connector.connect") as fake_connect:
            provider.execute_query("SELECT 1")
            fake_connect.assert_not_called()

    def test_db_error_is_wrapped_with_context(self):
        from mysql.connector import Error
        provider, conn, cursor = _provider_with_fake_conn()
        cursor.execute.side_effect = Error("syntax error near")

        try:
            provider.execute_query("SELECT bad sql")
            assert False, "expected an exception"
        except Exception as e:
            assert "Query execution failed" in str(e)


class TestExecuteQueryDefaultTimeout:
    def test_default_timeout_is_300s_when_not_configured(self):
        provider = MySQLProvider({"host": "h", "database": "d", "user": "u", "password": "p"})
        assert provider.timeout == 300

    def test_configured_timeout_overrides_default(self):
        provider = MySQLProvider({"host": "h", "database": "d", "user": "u", "password": "p", "timeout": 42})
        assert provider.timeout == 42


class TestExecuteQueryWatchdogTimeout:
    """timeout is set to a few tens of ms and the mocked cursor.execute()
    genuinely sleeps past it, so the real threading.Timer watchdog fires
    during that sleep — same mechanism as production, just compressed to
    keep the test fast."""

    def test_slow_query_kills_by_connection_id_and_raises_timeout_error(self):
        from mysql.connector import Error
        provider, conn, cursor = _provider_with_fake_conn(timeout=0.05, connection_id=987)

        def _slow_execute(sql):
            time.sleep(0.2)  # long enough for the 0.05s watchdog to fire first
            raise Error("Query execution was interrupted")  # KILL QUERY's real-world effect

        cursor.execute.side_effect = _slow_execute

        killer_cursor = MagicMock()
        killer_conn = MagicMock()
        killer_conn.cursor.return_value = killer_cursor

        with patch("src.providers.database.mysql_provider.mysql.connector.connect",
                   return_value=killer_conn) as fake_connect:
            try:
                provider.execute_query("SELECT SLEEP(10)")
                assert False, "expected TimeoutError"
            except TimeoutError as e:
                assert "0.05" in str(e)

            fake_connect.assert_called_once()
            killer_cursor.execute.assert_called_once()
            assert "KILL QUERY 987" in killer_cursor.execute.call_args[0][0]
        killer_conn.close.assert_called_once()

    def test_slow_query_succeeding_anyway_still_raises_timeout_error(self):
        # Race: the query finishes (and KILL QUERY was a no-op) right around
        # the timeout firing — treated as a timeout regardless, same as
        # TrinoProvider, rather than returning a result the caller never
        # asked to wait that long for.
        provider, conn, cursor = _provider_with_fake_conn(timeout=0.05, connection_id=1)

        def _slow_execute(sql):
            time.sleep(0.2)
            cursor.description = [("id",)]

        cursor.execute.side_effect = _slow_execute
        cursor.fetchall.return_value = [(1,)]

        with patch("src.providers.database.mysql_provider.mysql.connector.connect",
                   return_value=MagicMock()):
            try:
                provider.execute_query("SELECT SLEEP(10)")
                assert False, "expected TimeoutError"
            except TimeoutError:
                pass

    def test_killer_connection_failure_is_swallowed(self):
        # The killer connection itself failing (e.g. server unreachable)
        # must not crash the watchdog thread or surface as anything other
        # than the TimeoutError to the caller.
        provider, conn, cursor = _provider_with_fake_conn(timeout=0.05)

        def _slow_execute(sql):
            time.sleep(0.2)
            cursor.description = [("id",)]

        cursor.execute.side_effect = _slow_execute
        cursor.fetchall.return_value = [(1,)]

        with patch("src.providers.database.mysql_provider.mysql.connector.connect",
                   side_effect=Exception("connection refused")):
            try:
                provider.execute_query("SELECT SLEEP(10)")
                assert False, "expected TimeoutError"
            except TimeoutError:
                pass

    def test_timer_is_cancelled_on_fast_completion_no_stray_kill(self):
        provider, conn, cursor = _provider_with_fake_conn(timeout=0.05)
        cursor.description = [("id",)]
        cursor.fetchall.return_value = [(1,)]

        with patch("src.providers.database.mysql_provider.mysql.connector.connect") as fake_connect:
            provider.execute_query("SELECT 1")
            time.sleep(0.15)  # past the timeout window — watchdog must be dead by now
            fake_connect.assert_not_called()

    def test_zero_timeout_disables_the_watchdog_entirely(self):
        provider, conn, cursor = _provider_with_fake_conn(timeout=0)

        def _slow_execute(sql):
            time.sleep(0.1)
            cursor.description = [("id",)]

        cursor.execute.side_effect = _slow_execute
        cursor.fetchall.return_value = [(1,)]

        with patch("src.providers.database.mysql_provider.mysql.connector.connect") as fake_connect:
            columns, data = provider.execute_query("SELECT 1")
            fake_connect.assert_not_called()

        assert (columns, data) == (["id"], [[1]])
