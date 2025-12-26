"""
SQLatte Query History & Favorites Manager
Manages SQL query history and user favorites (in-memory with session support)
"""

import uuid
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict


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
    is_favorite: bool = False
    favorite_name: Optional[str] = None  # Custom name for favorites
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "sql": self.sql,
            "tables": self.tables,
            "row_count": self.row_count,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat(),
            "session_id": self.session_id,
            "is_favorite": self.is_favorite,
            "favorite_name": self.favorite_name,
            "tags": self.tags
        }

    def get_hash(self) -> str:
        """Generate hash for deduplication"""
        return hashlib.md5(self.sql.strip().lower().encode()).hexdigest()[:12]


class QueryHistoryManager:
    """
    Manages query history and favorites

    Features:
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
        self.history: Dict[str, List[QueryRecord]] = {}  # session_id -> queries
        self.favorites: Dict[str, QueryRecord] = {}  # query_id -> record
        self.max_history_per_session = max_history_per_session
        self.max_favorites = max_favorites
        self.history_retention_hours = history_retention_hours

        print(f"✅ Query History Manager initialized")
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
        tags: List[str] = None
    ) -> QueryRecord:
        """
        Add a query to history

        Args:
            session_id: User session ID
            question: Natural language question
            sql: Generated SQL query
            tables: List of tables used
            row_count: Number of rows returned
            execution_time_ms: Query execution time
            tags: Optional tags for categorization

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
            tags=tags or []
        )

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
        if session_id not in self.history:
            return []

        queries = self.history[session_id].copy()

        # Apply search filter
        if search:
            search_lower = search.lower()
            queries = [
                q for q in queries
                if search_lower in q.question.lower() or search_lower in q.sql.lower()
            ]

        # Apply tables filter
        if tables_filter:
            queries = [
                q for q in queries
                if any(t in q.tables for t in tables_filter)
            ]

        # Sort by most recent first
        queries.sort(key=lambda x: x.created_at, reverse=True)

        # Apply pagination
        paginated = queries[offset:offset + limit]

        return [q.to_dict() for q in paginated]

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
        2. Create new favorite from scratch (question + sql)

        Args:
            query_id: Existing query ID to mark as favorite
            session_id: Session ID (for new favorites)
            question: Natural language question (for new favorites)
            sql: SQL query (for new favorites)
            tables: Tables used
            favorite_name: Custom name for the favorite
            tags: Tags for categorization

        Returns:
            QueryRecord if successful, None otherwise
        """
        # Method 1: Mark existing query as favorite
        if query_id:
            for session_queries in self.history.values():
                for query in session_queries:
                    if query.id == query_id:
                        query.is_favorite = True
                        query.favorite_name = favorite_name or query.question[:50]
                        if tags:
                            query.tags = tags
                        self.favorites[query.id] = query
                        return query

        # Method 2: Create new favorite
        if question and sql:
            record = QueryRecord(
                id=str(uuid.uuid4()),
                question=question,
                sql=sql,
                tables=tables or [],
                row_count=0,
                execution_time_ms=0.0,
                created_at=datetime.now(),
                session_id=session_id or "global",
                is_favorite=True,
                favorite_name=favorite_name or question[:50],
                tags=tags or []
            )
            self.favorites[record.id] = record

            # Enforce max favorites limit
            if len(self.favorites) > self.max_favorites:
                # Remove oldest favorite
                oldest_id = min(
                    self.favorites.keys(),
                    key=lambda x: self.favorites[x].created_at
                )
                del self.favorites[oldest_id]

            return record

        return None

    def remove_from_favorites(self, query_id: str) -> bool:
        """Remove a query from favorites"""
        if query_id in self.favorites:
            self.favorites[query_id].is_favorite = False
            del self.favorites[query_id]
            return True

        # Also check in history
        for session_queries in self.history.values():
            for query in session_queries:
                if query.id == query_id:
                    query.is_favorite = False
                    query.favorite_name = None
                    return True

        return False

    def get_favorites(
        self,
        limit: int = 50,
        search: str = None,
        tags_filter: List[str] = None
    ) -> List[Dict]:
        """
        Get all favorites

        Args:
            limit: Max number of records
            search: Search term
            tags_filter: Filter by tags

        Returns:
            List of favorite query records
        """
        favorites = list(self.favorites.values())

        # Apply search filter
        if search:
            search_lower = search.lower()
            favorites = [
                f for f in favorites
                if search_lower in f.question.lower()
                or search_lower in f.sql.lower()
                or (f.favorite_name and search_lower in f.favorite_name.lower())
            ]

        # Apply tags filter
        if tags_filter:
            favorites = [
                f for f in favorites
                if any(t in f.tags for t in tags_filter)
            ]

        # Sort by name/question
        favorites.sort(key=lambda x: x.favorite_name or x.question)

        return [f.to_dict() for f in favorites[:limit]]

    def get_query_by_id(self, query_id: str) -> Optional[Dict]:
        """Get a specific query by ID"""
        # Check favorites first
        if query_id in self.favorites:
            return self.favorites[query_id].to_dict()

        # Check history
        for session_queries in self.history.values():
            for query in session_queries:
                if query.id == query_id:
                    return query.to_dict()

        return None

    def delete_query(self, query_id: str, session_id: str = None) -> bool:
        """Delete a query from history"""
        # Remove from favorites if present
        if query_id in self.favorites:
            del self.favorites[query_id]

        # Remove from history
        if session_id and session_id in self.history:
            self.history[session_id] = [
                q for q in self.history[session_id]
                if q.id != query_id
            ]
            return True

        # Search all sessions
        for sid, queries in self.history.items():
            for i, query in enumerate(queries):
                if query.id == query_id:
                    self.history[sid].pop(i)
                    return True

        return False

    def clear_history(self, session_id: str) -> int:
        """Clear all history for a session (keeps favorites)"""
        if session_id not in self.history:
            return 0

        count = len(self.history[session_id])

        # Keep favorites, remove rest
        self.history[session_id] = [
            q for q in self.history[session_id]
            if q.is_favorite
        ]

        return count - len(self.history[session_id])

    def cleanup_old_history(self) -> int:
        """Remove history older than retention period"""
        cutoff = datetime.now() - timedelta(hours=self.history_retention_hours)
        removed = 0

        for session_id in list(self.history.keys()):
            original_count = len(self.history[session_id])

            # Keep favorites and recent queries
            self.history[session_id] = [
                q for q in self.history[session_id]
                if q.is_favorite or q.created_at > cutoff
            ]

            removed += original_count - len(self.history[session_id])

            # Remove empty sessions
            if not self.history[session_id]:
                del self.history[session_id]

        if removed > 0:
            print(f"🧹 Cleaned up {removed} old history entries")

        return removed

    def get_stats(self) -> Dict:
        """Get statistics about history and favorites"""
        total_queries = sum(len(q) for q in self.history.values())

        # Most used tables
        table_counts: Dict[str, int] = {}
        for session_queries in self.history.values():
            for query in session_queries:
                for table in query.tables:
                    table_counts[table] = table_counts.get(table, 0) + 1

        top_tables = sorted(
            table_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        return {
            "total_sessions": len(self.history),
            "total_queries": total_queries,
            "total_favorites": len(self.favorites),
            "top_tables": dict(top_tables),
            "retention_hours": self.history_retention_hours
        }

    def get_recent_tables(self, session_id: str, limit: int = 5) -> List[str]:
        """Get most recently used tables for a session"""
        if session_id not in self.history:
            return []

        recent_queries = sorted(
            self.history[session_id],
            key=lambda x: x.created_at,
            reverse=True
        )[:10]

        # Flatten and dedupe tables
        seen = set()
        tables = []
        for query in recent_queries:
            for table in query.tables:
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
        for fav in self.favorites.values():
            if any(t in fav.tables for t in current_tables):
                suggestions.append({
                    "source": "favorite",
                    "query": fav.to_dict()
                })

        # 2. From history matching current tables
        if session_id in self.history:
            for query in reversed(self.history[session_id]):
                if any(t in query.tables for t in current_tables):
                    if not query.is_favorite:  # Don't duplicate favorites
                        suggestions.append({
                            "source": "history",
                            "query": query.to_dict()
                        })

        return suggestions[:limit]


# Global instance
query_history = QueryHistoryManager(
    max_history_per_session=50,
    max_favorites=100,
    history_retention_hours=24
)