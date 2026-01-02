"""
SQLatte Session Manager - Thread-Safe Authentication Sessions
"""

import uuid
import time
import threading
from typing import Dict, Optional, Any
from datetime import datetime, timedelta


class AuthSession:
    """Single authentication session"""

    def __init__(
            self,
            session_id: str,
            username: str,
            db_config: Dict[str, Any],
            ttl_minutes: int = 480  # 8 hours default
    ):
        self.session_id = session_id
        self.username = username
        self.db_config = db_config
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.ttl_minutes = ttl_minutes
        self.conversation_id = None  # Link to conversation manager session

    def is_expired(self) -> bool:
        """Check if session has expired"""
        elapsed = datetime.now() - self.last_activity
        return elapsed > timedelta(minutes=self.ttl_minutes)

    def touch(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "session_id": self.session_id,
            "username": self.username,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "ttl_minutes": self.ttl_minutes,
            "conversation_id": self.conversation_id
        }


class SessionManager:
    """
    Thread-safe session management for authenticated users

    Features:
    - Thread-safe session storage
    - Automatic session expiration
    - Session-specific database configurations
    - Background cleanup task
    """

    def __init__(self, session_ttl_minutes: int = 480):
        self.sessions: Dict[str, AuthSession] = {}
        self.session_ttl_minutes = session_ttl_minutes
        self._lock = threading.RLock()
        self._cleanup_interval = 300  # 5 minutes
        self._cleanup_thread = None
        self._running = False

        print(f"✅ Session Manager initialized (TTL: {session_ttl_minutes}min)")

    def create_session(
            self,
            username: str,
            db_config: Dict[str, Any]
    ) -> str:
        """
        Create a new authentication session

        Args:
            username: Username
            db_config: Database configuration for this session

        Returns:
            Session ID
        """
        session_id = str(uuid.uuid4())

        with self._lock:
            session = AuthSession(
                session_id=session_id,
                username=username,
                db_config=db_config,
                ttl_minutes=self.session_ttl_minutes
            )
            self.sessions[session_id] = session

        print(f"🆕 Session created: {username} ({session_id[:8]}...)")
        return session_id

    def get_session(self, session_id: str) -> Optional[AuthSession]:
        """
        Get session by ID

        Args:
            session_id: Session ID

        Returns:
            AuthSession or None if not found/expired
        """
        with self._lock:
            session = self.sessions.get(session_id)

            if not session:
                return None

            if session.is_expired():
                print(f"⏰ Session expired: {session.username} ({session_id[:8]}...)")
                del self.sessions[session_id]
                return None

            # Touch session (update last activity)
            session.touch()
            return session

    def validate_session(self, session_id: str) -> bool:
        """Check if session is valid"""
        return self.get_session(session_id) is not None

    def get_db_config(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get database configuration for session"""
        session = self.get_session(session_id)
        return session.db_config if session else None

    def link_conversation(self, session_id: str, conversation_id: str):
        """Link auth session to conversation session"""
        session = self.get_session(session_id)
        if session:
            session.conversation_id = conversation_id

    def destroy_session(self, session_id: str) -> bool:
        """Destroy a session"""
        with self._lock:
            if session_id in self.sessions:
                username = self.sessions[session_id].username
                del self.sessions[session_id]
                print(f"🗑️  Session destroyed: {username} ({session_id[:8]}...)")
                return True
        return False

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions"""
        with self._lock:
            expired = [
                sid for sid, session in self.sessions.items()
                if session.is_expired()
            ]

            for sid in expired:
                username = self.sessions[sid].username
                del self.sessions[sid]
                print(f"🧹 Cleaned expired session: {username} ({sid[:8]}...)")

            return len(expired)

    def start_cleanup_task(self):
        """Start background cleanup task"""
        if self._running:
            return

        self._running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True
        )
        self._cleanup_thread.start()
        print(f"🧹 Session cleanup task started (interval: {self._cleanup_interval}s)")

    def stop_cleanup_task(self):
        """Stop background cleanup task"""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
        print("🛑 Session cleanup task stopped")

    def _cleanup_loop(self):
        """Background cleanup loop"""
        while self._running:
            time.sleep(self._cleanup_interval)
            if self._running:
                count = self.cleanup_expired_sessions()
                if count > 0:
                    print(f"🧹 Auto-cleanup: {count} expired sessions removed")

    def get_stats(self) -> Dict[str, Any]:
        """Get session statistics"""
        with self._lock:
            active_sessions = [s for s in self.sessions.values() if not s.is_expired()]

            return {
                "total_sessions": len(self.sessions),
                "active_sessions": len(active_sessions),
                "session_ttl_minutes": self.session_ttl_minutes,
                "cleanup_interval_seconds": self._cleanup_interval,
                "cleanup_task_running": self._running
            }

    def list_sessions(self) -> list:
        """List all active sessions (for admin)"""
        with self._lock:
            return [
                session.to_dict()
                for session in self.sessions.values()
                if not session.is_expired()
            ]


# Global session manager instance
auth_session_manager = SessionManager(session_ttl_minutes=480)