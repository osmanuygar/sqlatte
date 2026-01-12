"""
SQLatte Query History & Favorites Manager
Manages SQL query history and user favorites with optional PostgreSQL persistence
"""

import uuid
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict

# PostgreSQL backend (optional)
from src.core.analytics_db_postgres import analytics_db


@dataclass
class QueryRecord:
    """Single query record"""
    id: str
    question: str  # Natural language question
    sql: str  # Generated SQL
    tables: List[str]  # Tables used
    row_count: int  # Number of rows returned
    execution_time_ms: float  # Execution time
    created_at: datetime
    session_id: str

    # Analytics fields
    success: bool = True
    error_message: Optional[str] = None
    widget_type: str = "default"  # 'default' or 'auth'
    user_id: Optional[str] = None

    is_favorite: bool = False
    favorite_name: Optional[str] = None  # Custom name for favorites
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "id": self.id,
            "question": self.question,
            "sql": self.sql,
            "tables": self.tables,
            "row_count": self.row_count,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "session_id": self.session_id,
            "success": self.success,
            "error_message": self.error_message,
            "widget_type": self.widget_type,
            "user_id": self.user_id,
            "is_favorite": self.is_favorite,
            "favorite_name": self.favorite_name,
            "tags": self.tags
        }

    def get_hash(self) -> str:
        """Generate hash for deduplication"""
        return hashlib.md5(self.sql.strip().lower().encode()).hexdigest()[:12]


class QueryHistoryManager:
    """
    Manages query history and favorites with optional PostgreSQL persistence

    Features:
    - Optional persistent storage with PostgreSQL
    - In-memory cache (always available)
    - Per-session query history
    - Global favorites (across sessions)
    - Deduplication
    - Auto-cleanup of old entries
    - Search and filter capabilities
    """

    def __init__(
        self,
        max_history_per_session: int = 50,
        max_favorites: int = 100,
        history_retention_hours: int = 24
    ):
        # PostgreSQL backend (optional - can be None)
        self.db = analytics_db

        # In-memory cache (always available)
        self.history: Dict[str, List[QueryRecord]] = {}  # session_id -> queries
        self.favorites: Dict[str, QueryRecord] = {}  # query_id -> record

        self.max_history_per_session = max_history_per_session
        self.max_favorites = max_favorites
        self.history_retention_hours = history_retention_hours

        print(f"✅ Query History Manager initialized")

        # Backend info
        if self.db is not None:
            try:
                db_info = f"{self.db.connection_params['database']}@{self.db.connection_params['host']}:{self.db.connection_params['port']}"
                print(f"   PostgreSQL backend: {db_info}")
            except (AttributeError, KeyError):
                print(f"   Backend: PostgreSQL")
        else:
            print(f"   Backend: In-memory only (no persistence)")

        print(f"   Max history/session: {max_history_per_session}")
        print(f"   Max favorites: {max_favorites}")
        print(f"   Retention: {history_retention_hours}h")

    def add_query(
        self,
        session_id: str,
        question: str,
        sql: str,
        tables: List[str],
        row_count: int = 0,
        execution_time_ms: float = 0.0,
        tags: List[str] = None,
        success: bool = True,
        error_message: str = None,
        widget_type: str = "default",
        user_id: str = None
    ) -> QueryRecord:
        """
        Add a query to history (both in-memory and PostgreSQL if available)

        Args:
            session_id: User session ID
            question: Natural language question
            sql: Generated SQL query
            tables: List of tables used
            row_count: Number of rows returned
            execution_time_ms: Query execution time
            tags: Optional tags for categorization
            success: Whether query succeeded
            error_message: Error message if failed
            widget_type: Widget type ('default' or 'auth')
            user_id: User ID (for auth widget)

        Returns:
            QueryRecord object
        """
        # Initialize session history if needed
        if session_id not in self.history:
            self.history[session_id] = []

        # Create record
        record = QueryRecord(
            id=str(uuid.uuid4()),
            question=question,
            sql=sql,
            tables=tables or [],
            row_count=row_count,
            execution_time_ms=execution_time_ms,
            created_at=datetime.now(),
            session_id=session_id,
            tags=tags or [],
            success=success,
            error_message=error_message,
            widget_type=widget_type,
            user_id=user_id
        )

        # Save to PostgreSQL (if available)
        if self.db is not None:
            self.db.save_query(record.to_dict())

        # Check for duplicates (same SQL in last 5 queries)
        recent_hashes = [q.get_hash() for q in self.history[session_id][-5:]]
        if record.get_hash() not in recent_hashes:
            self.history[session_id].append(record)

            # Enforce max history limit (FIFO)
            if len(self.history[session_id]) > self.max_history_per_session:
                # Remove oldest non-favorite
                for i, old_record in enumerate(self.history[session_id]):
                    if not old_record.is_favorite:
                        self.history[session_id].pop(i)
                        break

        return record

    def get_history(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
        search: str = None,
        tables_filter: List[str] = None
    ) -> List[Dict]:
        """
        Get query history for a session

        Args:
            session_id: User session ID
            limit: Max number of records
            offset: Pagination offset
            search: Search term (searches question and SQL)
            tables_filter: Filter by tables used

        Returns:
            List of query records
        """
        # Use PostgreSQL if available, otherwise in-memory
        if self.db is not None:
            # Get from PostgreSQL
            queries = self.db.get_queries(
                session_id=session_id,
                limit=limit,
                offset=offset
            )

            # Apply search filter (client-side)
            if search:
                search_lower = search.lower()
                queries = [
                    q for q in queries
                    if search_lower in q['question'].lower() or search_lower in q['sql'].lower()
                ]

            # Apply tables filter
            if tables_filter:
                queries = [
                    q for q in queries
                    if any(t in q['tables'] for t in tables_filter)
                ]

            return queries
        else:
            # In-memory fallback
            if session_id not in self.history:
                return []

            queries = [q.to_dict() for q in self.history[session_id]]

            # Apply filters
            if search:
                search_lower = search.lower()
                queries = [q for q in queries if search_lower in q['question'].lower() or search_lower in q['sql'].lower()]

            if tables_filter:
                queries = [q for q in queries if any(t in q['tables'] for t in tables_filter)]

            # Apply pagination
            return queries[offset:offset + limit]

    def add_to_favorites(
        self,
        query_id: str = None,
        session_id: str = None,
        question: str = None,
        sql: str = None,
        tables: List[str] = None,
        favorite_name: str = None,
        tags: List[str] = None
    ) -> Optional[QueryRecord]:
        """
        Add a query to favorites

        Can either:
        1. Mark existing query as favorite (by query_id)
        2. Create new favorite (by providing question, sql, tables)

        Args:
            query_id: Existing query ID to mark as favorite
            session_id: Session ID (for new favorites)
            question: Question text (for new favorites)
            sql: SQL text (for new favorites)
            tables: Tables list (for new favorites)
            favorite_name: Optional custom name
            tags: Optional tags

        Returns:
            QueryRecord if successful, None otherwise
        """
        if query_id:
            # Mark existing query as favorite
            if self.db is not None:
                success = self.db.update_favorite(query_id, True, favorite_name)
                if success:
                    query = self.db.get_query(query_id)
                    if query:
                        record = QueryRecord(**{
                            **query,
                            'created_at': datetime.fromisoformat(query['created_at']) if isinstance(query['created_at'], str) else query['created_at']
                        })
                        self.favorites[query_id] = record
                        return record
            else:
                # In-memory: Find and update
                for session_queries in self.history.values():
                    for q in session_queries:
                        if q.id == query_id:
                            q.is_favorite = True
                            q.favorite_name = favorite_name
                            self.favorites[query_id] = q
                            return q
            return None

        elif question and sql:
            # Create new favorite
            if len(self.favorites) >= self.max_favorites:
                print(f"⚠️ Favorites limit reached ({self.max_favorites})")
                return None

            record = self.add_query(
                session_id=session_id or "favorites",
                question=question,
                sql=sql,
                tables=tables or [],
                tags=tags or []
            )

            if self.db is not None:
                self.db.update_favorite(record.id, True, favorite_name)

            record.is_favorite = True
            record.favorite_name = favorite_name
            self.favorites[record.id] = record

            return record

        return None

    def remove_from_favorites(self, query_id: str) -> bool:
        """Remove a query from favorites"""
        if self.db is not None:
            success = self.db.update_favorite(query_id, False, None)
            if success and query_id in self.favorites:
                del self.favorites[query_id]
            return success
        else:
            # In-memory
            if query_id in self.favorites:
                self.favorites[query_id].is_favorite = False
                del self.favorites[query_id]
                return True
            return False

    def get_favorites(
        self,
        limit: int = 50,
        search: str = None
    ) -> List[Dict]:
        """
        Get all favorites

        Args:
            limit: Max records
            search: Search term

        Returns:
            List of favorite queries
        """
        if self.db is not None:
            # PostgreSQL
            with self.db.get_connection() as conn:
                with conn.cursor() as cursor:
                    query = "SELECT * FROM queries WHERE is_favorite = TRUE"
                    params = []

                    if search:
                        query += " AND (question ILIKE %s OR sql ILIKE %s)"
                        params.extend([f"%{search}%", f"%{search}%"])

                    query += " ORDER BY created_at DESC LIMIT %s"
                    params.append(limit)

                    cursor.execute(query, params)

                    results = []
                    for row in cursor.fetchall():
                        result = self.db._row_to_dict(row)
                        results.append(result)

                    return results
        else:
            # In-memory fallback
            favs = list(self.favorites.values())
            if search:
                search_lower = search.lower()
                favs = [f for f in favs if search_lower in f.question.lower() or search_lower in f.sql.lower()]
            return [f.to_dict() for f in favs[-limit:]]

    def delete_query(self, query_id: str, session_id: str) -> bool:
        """Delete a query from history"""
        if self.db is not None:
            # Delete from PostgreSQL
            success = self.db.delete_query(query_id)

            # Delete from in-memory cache
            if success and session_id in self.history:
                self.history[session_id] = [
                    q for q in self.history[session_id] if q.id != query_id
                ]

            return success
        else:
            # In-memory only
            if session_id in self.history:
                original_len = len(self.history[session_id])
                self.history[session_id] = [q for q in self.history[session_id] if q.id != query_id]
                return len(self.history[session_id]) < original_len
            return False

    def clear_history(self, session_id: str) -> int:
        """Clear all history for a session (keeps favorites)"""
        removed = 0

        # Clear in-memory
        if session_id in self.history:
            removed = sum(1 for q in self.history[session_id] if not q.is_favorite)
            self.history[session_id] = [
                q for q in self.history[session_id] if q.is_favorite
            ]

        # Clear from PostgreSQL (if available)
        if self.db is not None:
            with self.db.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        DELETE FROM queries
                        WHERE session_id = %s AND is_favorite = FALSE
                    """, (session_id,))

        return removed

    def get_stats(self) -> Dict:
        """Get statistics about history and favorites"""
        if self.db is not None:
            # PostgreSQL stats
            summary = self.db.get_analytics_summary(hours=24)

            return {
                "total_sessions": summary.get('unique_sessions', 0),
                "total_queries": summary.get('total_queries', 0),
                "total_favorites": len(self.get_favorites(limit=1000)),
                "top_tables": dict((t['table'], t['count']) for t in summary.get('top_tables', [])),
                "retention_hours": self.history_retention_hours,
                "success_rate": summary.get('success_rate', 0),
                "avg_execution_time_ms": summary.get('avg_execution_time_ms', 0),
                "backend": "postgresql"
            }
        else:
            # In-memory stats
            total_queries = sum(len(queries) for queries in self.history.values())
            return {
                "total_sessions": len(self.history),
                "total_queries": total_queries,
                "total_favorites": len(self.favorites),
                "top_tables": {},
                "retention_hours": self.history_retention_hours,
                "backend": "in-memory"
            }

    def get_recent_tables(self, session_id: str, limit: int = 5) -> List[str]:
        """Get most recently used tables for a session"""
        if self.db is not None:
            queries = self.db.get_queries(session_id=session_id, limit=10)
        else:
            if session_id not in self.history:
                return []
            queries = [q.to_dict() for q in self.history[session_id][-10:]]

        # Flatten and dedupe tables
        seen = set()
        tables = []
        for query in queries:
            for table in query.get('tables', []):
                if table not in seen:
                    seen.add(table)
                    tables.append(table)
                    if len(tables) >= limit:
                        return tables

        return tables

    def get_suggested_queries(
        self,
        session_id: str,
        current_tables: List[str],
        limit: int = 5
    ) -> List[Dict]:
        """
        Get suggested queries based on current context

        Args:
            session_id: User session
            current_tables: Currently selected tables
            limit: Max suggestions

        Returns:
            List of suggested queries
        """
        suggestions = []

        # 1. From favorites matching current tables
        favorites = self.get_favorites(limit=50)
        for fav in favorites:
            if any(t in fav.get('tables', []) for t in current_tables):
                suggestions.append({
                    "source": "favorite",
                    "query": fav
                })

        # 2. From recent history (same session, same tables)
        if self.db is not None:
            recent = self.db.get_queries(session_id=session_id, limit=20)
        else:
            if session_id in self.history:
                recent = [q.to_dict() for q in self.history[session_id][-20:]]
            else:
                recent = []

        for query in recent:
            if any(t in query.get('tables', []) for t in current_tables):
                if not any(s['query']['id'] == query['id'] for s in suggestions):
                    suggestions.append({
                        "source": "history",
                        "query": query
                    })

        return suggestions[:limit]


# Singleton instance
query_history = QueryHistoryManager()