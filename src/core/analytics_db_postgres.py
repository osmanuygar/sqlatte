"""
SQLatte Analytics Database - PostgreSQL Version
Production-ready with better concurrency than SQLite
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from contextlib import contextmanager


class AnalyticsDB:
    """PostgreSQL database for query history and analytics"""

    def __init__(
            self,
            host: str = "localhost",
            port: int = 5432,
            database: str = "sqllatte_analytics",
            user: str = "postgres",
            password: str = ""
    ):
        self.connection_params = {
            'host': host,
            'port': port,
            'database': database,
            'user': user,
            'password': password,
            'gssencmode': "disable"
        }
        self._init_db()
        print(f"✅ Analytics DB (PostgreSQL) initialized: {database}@{host}")

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
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
        """Create database schema"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS queries (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        user_id TEXT,
                        question TEXT NOT NULL,
                        sql TEXT NOT NULL,
                        tables JSONB DEFAULT '[]',
                        row_count INTEGER DEFAULT 0,
                        execution_time_ms REAL DEFAULT 0,
                        success BOOLEAN DEFAULT TRUE,
                        error_message TEXT,
                        widget_type TEXT DEFAULT 'default',
                        is_favorite BOOLEAN DEFAULT FALSE,
                        favorite_name TEXT,
                        tags JSONB DEFAULT '[]',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_session_id ON queries(session_id);
                    CREATE INDEX IF NOT EXISTS idx_user_id ON queries(user_id);
                    CREATE INDEX IF NOT EXISTS idx_widget_type ON queries(widget_type);
                    CREATE INDEX IF NOT EXISTS idx_created_at ON queries(created_at);
                    CREATE INDEX IF NOT EXISTS idx_success ON queries(success);
                    CREATE INDEX IF NOT EXISTS idx_is_favorite ON queries(is_favorite);
                """)

    def save_query(self, record_dict: Dict) -> bool:
        """Save a query record to database"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Handle created_at conversion
                    created_at = record_dict.get('created_at')
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    elif created_at is None:
                        created_at = datetime.now()

                    # Handle tables - ensure it's JSON string
                    tables_value = record_dict.get('tables', [])
                    if isinstance(tables_value, list):
                        tables_json = json.dumps(tables_value)
                    elif isinstance(tables_value, str):
                        tables_json = tables_value
                    else:
                        tables_json = json.dumps([])

                    cursor.execute("""
                        INSERT INTO queries (
                            id, session_id, user_id, question, sql, tables,
                            row_count, execution_time_ms, success, error_message,
                            widget_type, is_favorite, favorite_name, tags, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        record_dict['id'],
                        record_dict['session_id'],
                        record_dict.get('user_id'),
                        record_dict['question'],
                        record_dict['sql'],
                        tables_json,
                        record_dict.get('row_count', 0),
                        record_dict.get('execution_time_ms', 0),
                        record_dict.get('success', True),
                        record_dict.get('error_message'),
                        record_dict.get('widget_type', 'default'),
                        record_dict.get('is_favorite', False),
                        record_dict.get('favorite_name'),
                        json.dumps(record_dict.get('tags', [])),
                        created_at
                    ))
            return True
        except Exception as e:
            print(f"❌ Error saving query: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_query(self, query_id: str) -> Optional[Dict]:
        """Get a single query by ID"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM queries WHERE id = %s", (query_id,))
                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    # Parse JSON fields
                    result['tables'] = json.loads(result.get('tables', '[]')) if isinstance(result.get('tables'),
                                                                                            str) else result.get(
                        'tables', [])
                    result['tags'] = json.loads(result.get('tags', '[]')) if isinstance(result.get('tags'),
                                                                                        str) else result.get('tags', [])
                    return result
        return None

    def get_queries(
            self,
            session_id: Optional[str] = None,
            user_id: Optional[str] = None,
            widget_type: Optional[str] = None,
            success: Optional[bool] = None,
            limit: int = 100,
            offset: int = 0
    ) -> List[Dict]:
        """Get queries with filters"""
        query = "SELECT * FROM queries WHERE 1=1"
        params = []

        if session_id:
            query += " AND session_id = %s"
            params.append(session_id)

        if user_id:
            query += " AND user_id = %s"
            params.append(user_id)

        if widget_type:
            query += " AND widget_type = %s"
            params.append(widget_type)

        if success is not None:
            query += " AND success = %s"
            params.append(success)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                results = []
                for row in cursor.fetchall():
                    result = dict(row)
                    # Parse JSON fields
                    result['tables'] = json.loads(result.get('tables', '[]')) if isinstance(result.get('tables'),
                                                                                            str) else result.get(
                        'tables', [])
                    result['tags'] = json.loads(result.get('tags', '[]')) if isinstance(result.get('tags'),
                                                                                        str) else result.get('tags', [])
                    # Convert datetime to ISO string
                    if result.get('created_at'):
                        result['created_at'] = result['created_at'].isoformat()
                    results.append(result)
                return results

    def get_analytics_summary(self, hours: int = 24, widget_type: Optional[str] = None) -> Dict:
        """Get analytics summary"""
        cutoff = datetime.now() - timedelta(hours=hours)

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    widget_filter = ""
                    params = [cutoff]
                    if widget_type:
                        widget_filter = "AND widget_type = %s"
                        params.append(widget_type)

                    # Total queries
                    cursor.execute(f"""
                        SELECT COUNT(*) as total FROM queries
                        WHERE created_at >= %s {widget_filter}
                    """, params)
                    row = cursor.fetchone()
                    total = row['total'] if row else 0

                    # Success/failure
                    cursor.execute(f"""
                        SELECT 
                            COALESCE(SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END), 0) as successful,
                            COALESCE(SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END), 0) as failed
                        FROM queries WHERE created_at >= %s {widget_filter}
                    """, params)
                    row = cursor.fetchone()
                    successful = int(row['successful']) if row and row['successful'] else 0
                    failed = int(row['failed']) if row and row['failed'] else 0

                    # Avg execution time
                    cursor.execute(f"""
                        SELECT COALESCE(AVG(execution_time_ms), 0) as avg_time
                        FROM queries WHERE created_at >= %s AND success = TRUE {widget_filter}
                    """, params)
                    row = cursor.fetchone()
                    avg_time = float(row['avg_time']) if row and row['avg_time'] else 0.0

                    # Widget breakdown
                    cursor.execute("""
                        SELECT widget_type, COUNT(*) as count
                        FROM queries WHERE created_at >= %s
                        GROUP BY widget_type
                    """, [cutoff])
                    widget_breakdown = {}
                    for row in cursor.fetchall():
                        widget_breakdown[row['widget_type']] = int(row['count'])

                    # Top tables
                    cursor.execute(f"""
                        SELECT tables FROM queries
                        WHERE created_at >= %s AND success = TRUE {widget_filter}
                    """, params)

                    table_counts = {}
                    for row in cursor.fetchall():
                        if row['tables']:
                            tables_data = row['tables']

                            # Parse if string
                            if isinstance(tables_data, str):
                                try:
                                    tables_list = json.loads(tables_data)
                                except (json.JSONDecodeError, TypeError):
                                    continue
                            elif isinstance(tables_data, (list, dict)):
                                tables_list = tables_data
                            else:
                                continue

                            # Count tables
                            if isinstance(tables_list, list):
                                for table in tables_list:
                                    if table and isinstance(table, str):
                                        table_counts[table] = table_counts.get(table, 0) + 1
                            elif isinstance(tables_list, dict):
                                for table in tables_list.keys():
                                    if table and isinstance(table, str):
                                        table_counts[table] = table_counts.get(table, 0) + 1

                    top_tables = sorted(table_counts.items(), key=lambda x: x[1], reverse=True)[:10]

                    # Unique sessions/users
                    cursor.execute(f"""
                        SELECT 
                            COUNT(DISTINCT session_id) as sessions,
                            COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN user_id END) as users
                        FROM queries WHERE created_at >= %s {widget_filter}
                    """, params)
                    row = cursor.fetchone()
                    unique_sessions = int(row['sessions']) if row else 0
                    unique_users = int(row['users']) if row else 0

                    return {
                        "period_hours": hours,
                        "total_queries": total,
                        "successful_queries": successful,
                        "failed_queries": failed,
                        "success_rate": round((successful / total * 100) if total > 0 else 0, 2),
                        "avg_execution_time_ms": round(avg_time, 2),
                        "unique_sessions": unique_sessions,
                        "unique_users": unique_users,
                        "widget_breakdown": widget_breakdown,
                        "top_tables": [{"table": t, "count": c} for t, c in top_tables]
                    }

        except Exception as e:
            print(f"❌ Error in get_analytics_summary: {e}")
            import traceback
            traceback.print_exc()

            return {
                "period_hours": hours,
                "total_queries": 0,
                "successful_queries": 0,
                "failed_queries": 0,
                "success_rate": 0.0,
                "avg_execution_time_ms": 0.0,
                "unique_sessions": 0,
                "unique_users": 0,
                "widget_breakdown": {},
                "top_tables": []
            }

    def get_hourly_stats(self, hours: int = 24) -> List[Dict]:
        """Get hourly statistics"""
        cutoff = datetime.now() - timedelta(hours=hours)

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        date_trunc('hour', created_at) as hour,
                        COUNT(*) as total,
                        SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) as successful,
                        AVG(execution_time_ms) as avg_time
                    FROM queries
                    WHERE created_at >= %s
                    GROUP BY hour
                    ORDER BY hour
                """, [cutoff])

                return [{
                    "hour": row['hour'].isoformat(),
                    "total": row['total'],
                    "successful": row['successful'],
                    "avg_time": round(row['avg_time'] or 0, 2)
                } for row in cursor.fetchall()]

    def get_error_breakdown(self, hours: int = 24) -> List[Dict]:
        """Get error breakdown"""
        cutoff = datetime.now() - timedelta(hours=hours)

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT error_message, COUNT(*) as count
                    FROM queries
                    WHERE created_at >= %s AND success = FALSE
                    GROUP BY error_message
                    ORDER BY count DESC
                    LIMIT 10
                """, [cutoff])

                return [{"error": row['error_message'], "count": row['count']} for row in cursor.fetchall()]

    def update_favorite(self, query_id: str, is_favorite: bool, favorite_name: Optional[str] = None) -> bool:
        """Update favorite status"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE queries SET is_favorite = %s, favorite_name = %s WHERE id = %s
                    """, (is_favorite, favorite_name, query_id))
            return True
        except Exception as e:
            print(f"❌ Error updating favorite: {e}")
            return False

    def delete_query(self, query_id: str) -> bool:
        """Delete a query"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM queries WHERE id = %s", (query_id,))
            return True
        except Exception as e:
            print(f"❌ Error deleting query: {e}")
            return False

    def _row_to_dict(self, row) -> Dict:
        """Convert row to dictionary"""
        result = dict(row)
        # Parse JSON fields
        if 'tables' in result:
            result['tables'] = json.loads(result.get('tables', '[]')) if isinstance(result.get('tables'),
                                                                                    str) else result.get('tables', [])
        if 'tags' in result:
            result['tags'] = json.loads(result.get('tags', '[]')) if isinstance(result.get('tags'),
                                                                                str) else result.get('tags', [])
        # Convert datetime
        if result.get('created_at'):
            result['created_at'] = result['created_at'].isoformat()
        return result


# Singleton instance - Create from config (optional)
def create_analytics_db():
    """Create analytics DB from config (if enabled).

    Reads through config_manager rather than the raw YAML file, so a
    config_db-backed (encrypted) `analytics.postgresql.password` is honored
    just like it is for every other credential in the app.
    """
    try:
        from src.core.config_manager_enhanced import config_manager
        config = config_manager.get_config()

        # Check if analytics section exists
        if 'analytics' not in config:
            print("ℹ️  Analytics disabled: No 'analytics' section in config.yaml")
            return None

        analytics_config = config['analytics']

        # Check if enabled
        if not analytics_config.get('enabled', False):
            print("ℹ️  Analytics disabled in config.yaml")
            return None

        # Check backend
        backend = analytics_config.get('backend', 'postgresql')

        if backend != 'postgresql':
            print(f"⚠️  Analytics backend '{backend}' not supported, expected 'postgresql'")
            return None

        if 'postgresql' not in analytics_config:
            print("❌ PostgreSQL config not found in analytics.postgresql")
            return None

        pg_config = analytics_config['postgresql']

        # Check required fields
        required_fields = ['host', 'port', 'database', 'user']
        missing = [f for f in required_fields if f not in pg_config]

        if missing:
            print(f"❌ Missing required PostgreSQL fields: {missing}")
            return None

        db_config = {
            'host': pg_config['host'],
            'port': pg_config['port'],
            'database': pg_config['database'],
            'user': pg_config['user'],
            'password': pg_config.get('password', '')
        }

        print(f"📊 Initializing Analytics DB...")
        print(f"   Host: {db_config['host']}")
        print(f"   Database: {db_config['database']}")

        return AnalyticsDB(**db_config)

    except Exception as e:
        print(f"⚠️  Analytics initialization failed: {e}")
        print(f"   Analytics will be disabled")
        return None


# Singleton - Can be None if disabled
analytics_db = create_analytics_db()

if analytics_db is None:
    print("⚠️  Analytics DB is disabled - query history will not be persisted")