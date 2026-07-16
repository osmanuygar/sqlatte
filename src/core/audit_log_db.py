"""
SQLatte Audit Log Database
Tracks every LLM call: token usage, prompt preview, model, widget source
"""

import csv
import io
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from contextlib import contextmanager


class AuditLogDB:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "sqlatte_analytics",
        user: str = "postgres",
        password: str = "",
    ):
        self.connection_params = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
            "gssencmode": "disable",
        }
        self._init_db()
        print(f"✅ Audit Log DB initialized: {database}@{host}")

    @contextmanager
    def get_connection(self):
        conn = psycopg2.connect(**self.connection_params, cursor_factory=RealDictCursor)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_db(self):
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id             TEXT PRIMARY KEY,
                        session_id     TEXT NOT NULL,
                        user_id        TEXT,
                        widget_type    TEXT DEFAULT 'default',
                        question       TEXT,
                        operation_type TEXT NOT NULL,
                        model_name     TEXT,
                        prompt_preview TEXT,
                        input_tokens   INTEGER DEFAULT 0,
                        output_tokens  INTEGER DEFAULT 0,
                        total_tokens   INTEGER DEFAULT 0,
                        success        BOOLEAN DEFAULT TRUE,
                        catalog_name   TEXT,
                        table_names    TEXT,
                        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    ALTER TABLE audit_logs
                        ADD COLUMN IF NOT EXISTS widget_type   TEXT DEFAULT 'default';
                    ALTER TABLE audit_logs
                        ADD COLUMN IF NOT EXISTS catalog_name  TEXT;
                    ALTER TABLE audit_logs
                        ADD COLUMN IF NOT EXISTS table_names   TEXT;
                    ALTER TABLE audit_logs
                        ADD COLUMN IF NOT EXISTS generated_sql TEXT;
                    ALTER TABLE audit_logs
                        ADD COLUMN IF NOT EXISTS risk_score    INTEGER;
                    ALTER TABLE audit_logs
                        ADD COLUMN IF NOT EXISTS sql_valid     BOOLEAN;
                    ALTER TABLE audit_logs
                        ADD COLUMN IF NOT EXISTS execution_ms  INTEGER;

                    CREATE INDEX IF NOT EXISTS idx_audit_session_id  ON audit_logs(session_id);
                    CREATE INDEX IF NOT EXISTS idx_audit_operation    ON audit_logs(operation_type);
                    CREATE INDEX IF NOT EXISTS idx_audit_model        ON audit_logs(model_name);
                    CREATE INDEX IF NOT EXISTS idx_audit_widget       ON audit_logs(widget_type);
                    CREATE INDEX IF NOT EXISTS idx_audit_created_at   ON audit_logs(created_at);
                """)

    # ── Write ─────────────────────────────────────────────────────────────────

    def log(
        self,
        session_id: str,
        operation_type: str,
        model_name: str,
        question: str = "",
        prompt_preview: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        success: bool = True,
        user_id: Optional[str] = None,
        widget_type: str = "default",
        catalog_name: Optional[str] = None,
        table_names: Optional[List[str]] = None,
        generated_sql: Optional[str] = None,
        risk_score: Optional[int] = None,
        sql_valid: Optional[bool] = None,
        execution_ms: Optional[int] = None,
    ) -> str:
        entry_id = str(uuid.uuid4())
        table_names_str = ", ".join(table_names) if table_names else None
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO audit_logs
                            (id, session_id, user_id, widget_type, question,
                             operation_type, model_name, prompt_preview,
                             input_tokens, output_tokens, total_tokens,
                             success, catalog_name, table_names,
                             generated_sql, risk_score, sql_valid, execution_ms,
                             created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            entry_id,
                            session_id,
                            user_id,
                            widget_type,
                            (question or "")[:500],
                            operation_type,
                            model_name,
                            (prompt_preview or "")[:500],
                            input_tokens,
                            output_tokens,
                            input_tokens + output_tokens,
                            success,
                            catalog_name,
                            table_names_str,
                            generated_sql,
                            risk_score,
                            sql_valid,
                            execution_ms,
                            datetime.now(),
                        ),
                    )
        except Exception as e:
            print(f"❌ AuditLogDB.log error: {e}")
        return entry_id

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_logs(
        self,
        session_id: Optional[str] = None,
        operation_type: Optional[str] = None,
        model_name: Optional[str] = None,
        widget_type: Optional[str] = None,
        hours: int = 24,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        cutoff = datetime.now() - timedelta(hours=hours)
        query = "SELECT * FROM audit_logs WHERE created_at >= %s"
        params: list = [cutoff]

        if session_id:
            query += " AND session_id = %s"; params.append(session_id)
        if operation_type:
            query += " AND operation_type = %s"; params.append(operation_type)
        if model_name:
            query += " AND model_name = %s"; params.append(model_name)
        if widget_type:
            query += " AND widget_type = %s"; params.append(widget_type)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = []
                for row in cur.fetchall():
                    r = dict(row)
                    if r.get("created_at"):
                        r["created_at"] = r["created_at"].isoformat()
                    rows.append(r)
                return rows

    def get_summary(self, hours: int = 24) -> Dict:
        cutoff = datetime.now() - timedelta(hours=hours)
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            COUNT(*)                         AS total_calls,
                            COALESCE(SUM(input_tokens),  0) AS total_input_tokens,
                            COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
                            COALESCE(SUM(total_tokens),  0) AS total_tokens,
                            COALESCE(AVG(total_tokens),  0) AS avg_tokens_per_call
                        FROM audit_logs WHERE created_at >= %s
                    """, [cutoff])
                    row = dict(cur.fetchone())

                    cur.execute("""
                        SELECT model_name,
                               COUNT(*)                         AS calls,
                               COALESCE(SUM(total_tokens),  0) AS total_tokens
                        FROM audit_logs WHERE created_at >= %s
                        GROUP BY model_name ORDER BY total_tokens DESC
                    """, [cutoff])
                    by_model = [dict(r) for r in cur.fetchall()]

                    cur.execute("""
                        SELECT operation_type,
                               COUNT(*)                         AS calls,
                               COALESCE(SUM(total_tokens),  0) AS total_tokens
                        FROM audit_logs WHERE created_at >= %s
                        GROUP BY operation_type ORDER BY calls DESC
                    """, [cutoff])
                    by_operation = [dict(r) for r in cur.fetchall()]

                    cur.execute("""
                        SELECT widget_type,
                               COUNT(*)                         AS calls,
                               COALESCE(SUM(total_tokens),  0) AS total_tokens
                        FROM audit_logs WHERE created_at >= %s
                        GROUP BY widget_type ORDER BY calls DESC
                    """, [cutoff])
                    by_widget = [dict(r) for r in cur.fetchall()]

                    cur.execute("""
                        SELECT date_trunc('hour', created_at) AS hour,
                               COUNT(*)                        AS calls,
                               COALESCE(SUM(total_tokens), 0) AS total_tokens
                        FROM audit_logs WHERE created_at >= %s
                        GROUP BY hour ORDER BY hour
                    """, [cutoff])
                    hourly = [
                        {"hour": r["hour"].isoformat(), "calls": r["calls"],
                         "total_tokens": int(r["total_tokens"])}
                        for r in cur.fetchall()
                    ]

                    return {
                        "period_hours": hours,
                        "total_calls": int(row["total_calls"]),
                        "total_input_tokens": int(row["total_input_tokens"]),
                        "total_output_tokens": int(row["total_output_tokens"]),
                        "total_tokens": int(row["total_tokens"]),
                        "avg_tokens_per_call": round(float(row["avg_tokens_per_call"]), 1),
                        "by_model": by_model,
                        "by_operation": by_operation,
                        "by_widget": by_widget,
                        "hourly": hourly,
                    }
        except Exception as e:
            print(f"❌ AuditLogDB.get_summary error: {e}")
            import traceback; traceback.print_exc()
            return {
                "period_hours": hours, "total_calls": 0,
                "total_input_tokens": 0, "total_output_tokens": 0,
                "total_tokens": 0, "avg_tokens_per_call": 0.0,
                "by_model": [], "by_operation": [], "by_widget": [], "hourly": [],
            }

    def get_user_stats(self, user_id: str) -> Dict:
        """Token usage stats for a specific user (today and last 7 days)."""
        now = datetime.now()
        today_cutoff = now - timedelta(hours=24)
        week_cutoff = now - timedelta(hours=168)
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            COUNT(*)                         AS total_calls,
                            COALESCE(SUM(input_tokens),  0) AS total_input_tokens,
                            COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
                            COALESCE(SUM(total_tokens),  0) AS total_tokens,
                            COUNT(DISTINCT question)         AS unique_queries
                        FROM audit_logs
                        WHERE user_id = %s AND created_at >= %s
                    """, [user_id, today_cutoff])
                    today = dict(cur.fetchone())

                    cur.execute("""
                        SELECT
                            COUNT(*)                         AS total_calls,
                            COALESCE(SUM(input_tokens),  0) AS total_input_tokens,
                            COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
                            COALESCE(SUM(total_tokens),  0) AS total_tokens,
                            COUNT(DISTINCT question)         AS unique_queries
                        FROM audit_logs
                        WHERE user_id = %s AND created_at >= %s
                    """, [user_id, week_cutoff])
                    week = dict(cur.fetchone())

                    cur.execute("""
                        SELECT operation_type,
                               COUNT(*)                        AS calls,
                               COALESCE(SUM(total_tokens), 0) AS total_tokens
                        FROM audit_logs
                        WHERE user_id = %s AND created_at >= %s
                        GROUP BY operation_type ORDER BY calls DESC
                    """, [user_id, week_cutoff])
                    by_operation = [dict(r) for r in cur.fetchall()]

                    return {
                        "today": {
                            "calls": int(today["total_calls"]),
                            "queries": int(today["unique_queries"]),
                            "input_tokens": int(today["total_input_tokens"]),
                            "output_tokens": int(today["total_output_tokens"]),
                            "total_tokens": int(today["total_tokens"]),
                        },
                        "week": {
                            "calls": int(week["total_calls"]),
                            "queries": int(week["unique_queries"]),
                            "input_tokens": int(week["total_input_tokens"]),
                            "output_tokens": int(week["total_output_tokens"]),
                            "total_tokens": int(week["total_tokens"]),
                        },
                        "by_operation": by_operation,
                    }
        except Exception as e:
            print(f"❌ AuditLogDB.get_user_stats error: {e}")
            import traceback; traceback.print_exc()
            return {
                "today": {"calls": 0, "queries": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "week": {"calls": 0, "queries": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "by_operation": [],
            }

    def get_daily_trend(self, days: int = 30) -> Dict:
        """Daily SQL-generation volume trend, zero-filled for gap-free charting."""
        today = datetime.now().date()
        start_day = today - timedelta(days=days - 1)
        cutoff = datetime.combine(start_day, datetime.min.time())
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT date_trunc('day', created_at)::date AS day,
                               COUNT(*)                                    AS query_count,
                               SUM(CASE WHEN success THEN 1 ELSE 0 END)    AS successful,
                               COALESCE(SUM(total_tokens), 0)              AS total_tokens
                        FROM audit_logs
                        WHERE created_at >= %s AND operation_type = 'sql_generation'
                        GROUP BY day ORDER BY day
                    """, [cutoff])
                    by_day = {r["day"]: dict(r) for r in cur.fetchall()}

                    days_out = []
                    total_query_count = 0
                    total_successful = 0
                    total_tokens = 0
                    for i in range(days):
                        d = start_day + timedelta(days=i)
                        row = by_day.get(d)
                        qc = int(row["query_count"]) if row else 0
                        succ = int(row["successful"]) if row else 0
                        tok = int(row["total_tokens"]) if row else 0
                        days_out.append({
                            "date": d.isoformat(),
                            "query_count": qc,
                            "successful": succ,
                            "success_rate": round(succ / qc * 100, 1) if qc else 0.0,
                            "total_tokens": tok,
                        })
                        total_query_count += qc
                        total_successful += succ
                        total_tokens += tok

                    return {
                        "period_days": days,
                        "total_query_count": total_query_count,
                        "total_successful": total_successful,
                        "overall_success_rate": round(total_successful / total_query_count * 100, 1) if total_query_count else 0.0,
                        "total_tokens": total_tokens,
                        "avg_queries_per_day": round(total_query_count / days, 1) if days else 0.0,
                        # Anonymous/default-widget rows (user_id IS NULL) are counted here but
                        # excluded from get_top_users, so this total can exceed the sum of
                        # per-user query counts there — that's expected, not a bug.
                        "days": days_out,
                    }
        except Exception as e:
            print(f"❌ AuditLogDB.get_daily_trend error: {e}")
            import traceback; traceback.print_exc()
            return {
                "period_days": days, "total_query_count": 0, "total_successful": 0,
                "overall_success_rate": 0.0, "total_tokens": 0, "avg_queries_per_day": 0.0,
                "days": [],
            }

    def get_top_users(self, days: int = 30, limit: int = 10) -> Dict:
        """Top-N users by SQL-generation query count over the given period."""
        cutoff = datetime.now() - timedelta(days=days)
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COUNT(DISTINCT user_id) AS n
                        FROM audit_logs
                        WHERE created_at >= %s AND operation_type = 'sql_generation' AND user_id IS NOT NULL
                    """, [cutoff])
                    total_distinct_users = int(cur.fetchone()["n"])

                    cur.execute("""
                        SELECT user_id,
                               COUNT(*)                                    AS query_count,
                               COALESCE(SUM(input_tokens), 0)              AS input_tokens,
                               COALESCE(SUM(output_tokens), 0)             AS output_tokens,
                               COALESCE(SUM(total_tokens), 0)              AS total_tokens,
                               SUM(CASE WHEN success THEN 1 ELSE 0 END)    AS successful,
                               MAX(created_at)                             AS last_active
                        FROM audit_logs
                        WHERE created_at >= %s AND operation_type = 'sql_generation' AND user_id IS NOT NULL
                        GROUP BY user_id
                        ORDER BY query_count DESC
                        LIMIT %s
                    """, [cutoff, limit])

                    users = []
                    for r in cur.fetchall():
                        row = dict(r)
                        qc = int(row["query_count"])
                        succ = int(row["successful"])
                        tot = int(row["total_tokens"])
                        users.append({
                            "user_id": row["user_id"],
                            "query_count": qc,
                            "input_tokens": int(row["input_tokens"]),
                            "output_tokens": int(row["output_tokens"]),
                            "total_tokens": tot,
                            "successful": succ,
                            "success_rate": round(succ / qc * 100, 1) if qc else 0.0,
                            "avg_tokens_per_query": round(tot / qc, 1) if qc else 0.0,
                            "last_active": row["last_active"].isoformat() if row["last_active"] else None,
                        })

                    return {
                        "period_days": days,
                        "total_distinct_users": total_distinct_users,
                        "users": users,
                    }
        except Exception as e:
            print(f"❌ AuditLogDB.get_top_users error: {e}")
            import traceback; traceback.print_exc()
            return {"period_days": days, "total_distinct_users": 0, "users": []}

    def export_csv(
        self,
        session_id: Optional[str] = None,
        operation_type: Optional[str] = None,
        widget_type: Optional[str] = None,
        hours: int = 24,
    ) -> str:
        logs = self.get_logs(
            session_id=session_id,
            operation_type=operation_type,
            widget_type=widget_type,
            hours=hours,
            limit=10000,
        )
        columns = [
            "created_at", "widget_type", "operation_type", "model_name",
            "catalog_name", "table_names", "question", "prompt_preview",
            "input_tokens", "output_tokens", "total_tokens",
            "user_id", "session_id", "success",
            "generated_sql", "risk_score", "sql_valid", "execution_ms",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(logs)
        return buf.getvalue()


# ── Singleton factory ─────────────────────────────────────────────────────────

def create_audit_log_db() -> Optional[AuditLogDB]:
    """Create the audit log DB from config (if enabled).

    Reads through config_manager rather than the raw YAML file, so a
    config_db-backed (encrypted) `analytics.postgresql.password` is honored
    just like it is for every other credential in the app.
    """
    try:
        from src.core.config_manager_enhanced import config_manager
        config = config_manager.get_config()

        analytics = config.get("analytics", {})
        if not analytics.get("enabled", False):
            print("ℹ️  Audit logs disabled: analytics not enabled")
            return None

        pg = analytics.get("postgresql", {})
        return AuditLogDB(
            host=pg.get("host", "localhost"),
            port=int(pg.get("port", 5432)),
            database=pg.get("database", "sqlatte_analytics"),
            user=pg.get("user", "postgres"),
            password=pg.get("password", ""),
        )
    except Exception as e:
        print(f"⚠️  Audit Log DB init failed: {e}")
        return None


audit_log_db: Optional[AuditLogDB] = create_audit_log_db()
