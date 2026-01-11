# src/core/analytics_db.py
"""
SQLatte Analytics Database
SQLite-based persistent storage for query history and analytics
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager


class AnalyticsDB:
    """SQLite database for query history and analytics"""

    def __init__(self, db_path: str = "data/sqllatte.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()
        print(f"✅ Analytics DB initialized: {self.db_path}")

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dictionaries
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
            conn.executescript("""
                -- Query History Table
                CREATE TABLE IF NOT EXISTS queries (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT,
                    question TEXT NOT NULL,
                    sql TEXT NOT NULL,
                    tables TEXT,  -- JSON array
                    row_count INTEGER DEFAULT 0,
                    execution_time_ms REAL DEFAULT 0,
                    success BOOLEAN DEFAULT 1,
                    error_message TEXT,
                    widget_type TEXT DEFAULT 'default',
                    is_favorite BOOLEAN DEFAULT 0,
                    favorite_name TEXT,
                    tags TEXT,  -- JSON array
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Indexes for performance
                CREATE INDEX IF NOT EXISTS idx_session_id 
                    ON queries(session_id);
                CREATE INDEX IF NOT EXISTS idx_user_id 
                    ON queries(user_id);
                CREATE INDEX IF NOT EXISTS idx_widget_type 
                    ON queries(widget_type);
                CREATE INDEX IF NOT EXISTS idx_created_at 
                    ON queries(created_at);
                CREATE INDEX IF NOT EXISTS idx_success 
                    ON queries(success);
                CREATE INDEX IF NOT EXISTS idx_is_favorite 
                    ON queries(is_favorite);
            """)

    def save_query(self, record_dict: Dict) -> bool:
        """
        Save a query record to database

        Args:
            record_dict: Query record as dictionary

        Returns:
            True if successful
        """
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    INSERT INTO queries (
                        id, session_id, user_id, question, sql, tables,
                        row_count, execution_time_ms, success, error_message,
                        widget_type, is_favorite, favorite_name, tags, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record_dict['id'],
                    record_dict['session_id'],
                    record_dict.get('user_id'),
                    record_dict['question'],
                    record_dict['sql'],
                    json.dumps(record_dict.get('tables', [])),
                    record_dict.get('row_count', 0),
                    record_dict.get('execution_time_ms', 0),
                    record_dict.get('success', True),
                    record_dict.get('error_message'),
                    record_dict.get('widget_type', 'default'),
                    record_dict.get('is_favorite', False),
                    record_dict.get('favorite_name'),
                    json.dumps(record_dict.get('tags', [])),
                    record_dict.get('created_at', datetime.now().isoformat())
                ))
            return True
        except Exception as e:
            print(f"❌ Error saving query: {e}")
            return False

    def get_query(self, query_id: str) -> Optional[Dict]:
        """Get a single query by ID"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM queries WHERE id = ?",
                (query_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
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
        """
        Get queries with filters

        Args:
            session_id: Filter by session
            user_id: Filter by user
            widget_type: Filter by widget type
            success: Filter by success status
            limit: Max records
            offset: Pagination offset

        Returns:
            List of query records
        """
        query = "SELECT * FROM queries WHERE 1=1"
        params = []

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        if widget_type:
            query += " AND widget_type = ?"
            params.append(widget_type)

        if success is not None:
            query += " AND success = ?"
            params.append(success)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self.get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_analytics_summary(
            self,
            hours: int = 24,
            widget_type: Optional[str] = None
    ) -> Dict:
        """
        Get analytics summary for dashboard

        Args:
            hours: Time range in hours
            widget_type: Filter by widget type

        Returns:
            Analytics summary dictionary
        """
        cutoff = datetime.now().timestamp() - (hours * 3600)
        cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()

        with self.get_connection() as conn:
            # Base query filter
            widget_filter = ""
            params = [cutoff_iso]
            if widget_type:
                widget_filter = "AND widget_type = ?"
                params.append(widget_type)

            # Total queries
            cursor = conn.execute(f"""
                SELECT COUNT(*) as total
                FROM queries
                WHERE created_at >= ? {widget_filter}
            """, params)
            total = cursor.fetchone()['total']

            # Success/failure counts
            cursor = conn.execute(f"""
                SELECT 
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed
                FROM queries
                WHERE created_at >= ? {widget_filter}
            """, params)
            row = cursor.fetchone()
            successful = row['successful'] or 0
            failed = row['failed'] or 0

            # Average execution time
            cursor = conn.execute(f"""
                SELECT AVG(execution_time_ms) as avg_time
                FROM queries
                WHERE created_at >= ? AND success = 1 {widget_filter}
            """, params)
            avg_time = cursor.fetchone()['avg_time'] or 0

            # Widget breakdown
            cursor = conn.execute("""
                SELECT 
                    widget_type,
                    COUNT(*) as count
                FROM queries
                WHERE created_at >= ?
                GROUP BY widget_type
            """, [cutoff_iso])
            widget_breakdown = {row['widget_type']: row['count']
                                for row in cursor.fetchall()}

            # Top tables
            cursor = conn.execute(f"""
                SELECT tables
                FROM queries
                WHERE created_at >= ? AND success = 1 {widget_filter}
            """, params)

            table_counts = {}
            for row in cursor.fetchall():
                tables = json.loads(row['tables'] or '[]')
                for table in tables:
                    table_counts[table] = table_counts.get(table, 0) + 1

            top_tables = sorted(
                table_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]

            # Unique sessions and users
            cursor = conn.execute(f"""
                SELECT 
                    COUNT(DISTINCT session_id) as sessions,
                    COUNT(DISTINCT user_id) as users
                FROM queries
                WHERE created_at >= ? {widget_filter}
            """, params)
            row = cursor.fetchone()

            return {
                "period_hours": hours,
                "total_queries": total,
                "successful_queries": successful,
                "failed_queries": failed,
                "success_rate": round((successful / total * 100) if total > 0 else 0, 2),
                "avg_execution_time_ms": round(avg_time, 2),
                "unique_sessions": row['sessions'],
                "unique_users": row['users'],
                "widget_breakdown": widget_breakdown,
                "top_tables": [{"table": t, "count": c} for t, c in top_tables]
            }

    def get_hourly_stats(self, hours: int = 24) -> List[Dict]:
        """Get hourly query statistics"""
        cutoff = datetime.now().timestamp() - (hours * 3600)
        cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()

        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    strftime('%Y-%m-%d %H:00:00', created_at) as hour,
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    AVG(execution_time_ms) as avg_time
                FROM queries
                WHERE created_at >= ?
                GROUP BY hour
                ORDER BY hour
            """, [cutoff_iso])

            return [{
                "hour": row['hour'],
                "total": row['total'],
                "successful": row['successful'],
                "avg_time": round(row['avg_time'] or 0, 2)
            } for row in cursor.fetchall()]

    def get_error_breakdown(self, hours: int = 24) -> List[Dict]:
        """Get error types breakdown"""
        cutoff = datetime.now().timestamp() - (hours * 3600)
        cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()

        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    error_message,
                    COUNT(*) as count
                FROM queries
                WHERE created_at >= ? AND success = 0
                GROUP BY error_message
                ORDER BY count DESC
                LIMIT 10
            """, [cutoff_iso])

            return [{
                "error": row['error_message'],
                "count": row['count']
            } for row in cursor.fetchall()]

    def update_favorite(self, query_id: str, is_favorite: bool,
                        favorite_name: Optional[str] = None) -> bool:
        """Update favorite status of a query"""
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    UPDATE queries
                    SET is_favorite = ?, favorite_name = ?
                    WHERE id = ?
                """, (is_favorite, favorite_name, query_id))
            return True
        except Exception as e:
            print(f"❌ Error updating favorite: {e}")
            return False

    def delete_query(self, query_id: str) -> bool:
        """Delete a query"""
        try:
            with self.get_connection() as conn:
                conn.execute("DELETE FROM queries WHERE id = ?", (query_id,))
            return True
        except Exception as e:
            print(f"❌ Error deleting query: {e}")
            return False

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Convert SQLite row to dictionary"""
        return {
            "id": row['id'],
            "session_id": row['session_id'],
            "user_id": row['user_id'],
            "question": row['question'],
            "sql": row['sql'],
            "tables": json.loads(row['tables'] or '[]'),
            "row_count": row['row_count'],
            "execution_time_ms": row['execution_time_ms'],
            "success": bool(row['success']),
            "error_message": row['error_message'],
            "widget_type": row['widget_type'],
            "is_favorite": bool(row['is_favorite']),
            "favorite_name": row['favorite_name'],
            "tags": json.loads(row['tags'] or '[]'),
            "created_at": row['created_at']
        }


# Singleton instance
analytics_db = AnalyticsDB()