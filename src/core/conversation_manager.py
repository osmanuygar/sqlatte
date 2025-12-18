"""
SQLatte Conversation Manager
Manages conversation history per session (in-memory)
"""

import uuid
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta


class ConversationMessage:
    """Single message in a conversation"""

    def __init__(self, role: str, content: str, metadata: dict = None):
        self.role = role  # "user" or "assistant"
        self.content = content
        self.metadata = metadata or {}
        self.timestamp = datetime.now()

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }

    def to_llm_format(self) -> dict:
        """Format for LLM API"""
        return {
            "role": self.role,
            "content": self.content
        }


class ConversationSession:
    """Manages a single conversation session"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: List[ConversationMessage] = []
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.metadata = {}

    def add_message(self, role: str, content: str, metadata: dict = None):
        """Add a message to the conversation"""
        message = ConversationMessage(role, content, metadata)
        self.messages.append(message)
        self.last_activity = datetime.now()

    def get_messages(self, limit: int = None) -> List[ConversationMessage]:
        """Get conversation messages (most recent first if limit)"""
        if limit:
            return self.messages[-limit:]
        return self.messages

    def get_llm_context(self, max_messages: int = 10) -> List[dict]:
        """
        Get recent messages formatted for LLM context

        Args:
            max_messages: Maximum number of recent messages to include

        Returns:
            List of messages in LLM format
        """
        recent_messages = self.messages[-max_messages:]
        return [msg.to_llm_format() for msg in recent_messages]

    def clear(self):
        """Clear conversation history"""
        self.messages = []
        self.last_activity = datetime.now()

    def is_expired(self, timeout_minutes: int = 60) -> bool:
        """Check if session has expired"""
        elapsed = datetime.now() - self.last_activity
        return elapsed > timedelta(minutes=timeout_minutes)

    def get_summary(self) -> dict:
        """Get session summary"""
        return {
            "session_id": self.session_id,
            "message_count": len(self.messages),
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "duration_minutes": (datetime.now() - self.created_at).total_seconds() / 60
        }

    def to_dict(self) -> dict:
        """Convert session to dictionary"""
        return {
            "session_id": self.session_id,
            "messages": [msg.to_dict() for msg in self.messages],
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "metadata": self.metadata
        }


class ConversationManager:
    """
    Manages multiple conversation sessions (in-memory)

    Features:
    - Session-based conversation tracking
    - Automatic session cleanup
    - Context management for LLM
    - Conversation history
    """

    def __init__(self, session_timeout_minutes: int = 60):
        self.sessions: Dict[str, ConversationSession] = {}
        self.session_timeout_minutes = session_timeout_minutes
        self.max_context_messages = 10  # How many messages to send to LLM

        print(f"✅ Conversation Manager initialized (timeout: {session_timeout_minutes}min)")

    def create_session(self) -> str:
        """Create a new conversation session"""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = ConversationSession(session_id)
        return session_id

    def get_or_create_session(self, session_id: str = None) -> tuple[str, ConversationSession]:
        """
        Get existing session or create new one

        Returns:
            (session_id, session)
        """
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]

            # Check if expired
            if session.is_expired(self.session_timeout_minutes):
                print(f"⏰ Session {session_id[:8]}... expired, creating new")
                del self.sessions[session_id]
                session_id = self.create_session()
                session = self.sessions[session_id]

            return session_id, session
        else:
            # Create new session
            session_id = self.create_session()
            session = self.sessions[session_id]
            print(f"🆕 New session created: {session_id[:8]}...")
            return session_id, session

    def add_message(
            self,
            session_id: str,
            role: str,
            content: str,
            metadata: dict = None
    ):
        """Add message to session"""
        _, session = self.get_or_create_session(session_id)
        session.add_message(role, content, metadata)

    def get_conversation_context(
            self,
            session_id: str,
            system_prompt: str = None
    ) -> List[dict]:
        """
        Get conversation context for LLM

        Args:
            session_id: Session identifier
            system_prompt: Optional system prompt to prepend

        Returns:
            List of messages formatted for LLM
        """
        _, session = self.get_or_create_session(session_id)

        context = []

        # Add system prompt if provided
        if system_prompt:
            context.append({
                "role": "system",
                "content": system_prompt
            })

        # Add recent conversation history
        context.extend(session.get_llm_context(self.max_context_messages))

        return context

    def get_session_history(self, session_id: str) -> List[dict]:
        """Get full conversation history for a session"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            return [msg.to_dict() for msg in session.messages]
        return []

    def clear_session(self, session_id: str):
        """Clear a session's conversation history"""
        if session_id in self.sessions:
            self.sessions[session_id].clear()

    def delete_session(self, session_id: str):
        """Delete a session completely"""
        if session_id in self.sessions:
            del self.sessions[session_id]

    def cleanup_expired_sessions(self):
        """Remove expired sessions"""
        expired = [
            sid for sid, session in self.sessions.items()
            if session.is_expired(self.session_timeout_minutes)
        ]

        for sid in expired:
            del self.sessions[sid]

        if expired:
            print(f"🧹 Cleaned up {len(expired)} expired sessions")

        return len(expired)

    def get_stats(self) -> dict:
        """Get conversation manager statistics"""
        total_messages = sum(len(s.messages) for s in self.sessions.values())

        active_sessions = [
            s for s in self.sessions.values()
            if not s.is_expired(self.session_timeout_minutes)
        ]

        return {
            "total_sessions": len(self.sessions),
            "active_sessions": len(active_sessions),
            "total_messages": total_messages,
            "avg_messages_per_session": total_messages / len(self.sessions) if self.sessions else 0,
            "session_timeout_minutes": self.session_timeout_minutes
        }

    def get_session_summary(self, session_id: str) -> Optional[dict]:
        """Get summary for a specific session"""
        if session_id in self.sessions:
            return self.sessions[session_id].get_summary()
        return None


# Global conversation manager instance
conversation_manager = ConversationManager(session_timeout_minutes=60)