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
                        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    ALTER TABLE audit_logs
                        ADD COLUMN IF NOT EXISTS widget_type TEXT DEFAULT 'default';

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
    ) -> str:
        entry_id = str(uuid.uuid4())
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO audit_logs
                            (id, session_id, user_id, widget_type, question,
                             operation_type, model_name, prompt_preview,
                             input_tokens, output_tokens, total_tokens,
                             success, created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            "question", "prompt_preview", "input_tokens", "output_tokens",
            "total_tokens", "user_id", "session_id", "success",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(logs)
        return buf.getvalue()


# ── Singleton factory ─────────────────────────────────────────────────────────

def create_audit_log_db() -> Optional[AuditLogDB]:
    import os, yaml
    try:
        PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        with open(os.path.join(PROJECT_ROOT, "config", "config.yaml")) as f:
            config = yaml.safe_load(f)

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
